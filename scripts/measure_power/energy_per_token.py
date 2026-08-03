"""Tính Joule trên mỗi token — chỉ số chủ đạo của ESG Tầng 1.

Đây là hiện thực tham chiếu của công thức trong docs/07-esg-3-tang.md §3.1:

    energy_j    = ∫ P(t) dt trên khoảng chạy job   (tích phân hình thang)
    J_per_token = Σ energy_j / Σ tokens_out

Script đọc hai nguồn:

  * telemetry.db  — chuỗi thời gian công suất, do agent gửi về server
  * danh sách job — mỗi job có (node, thời điểm bắt đầu/kết thúc, số token)

Danh sách job lấy từ bảng `esg_events` nếu đã có, hoặc từ một tệp CSV. Nhờ
đường CSV, script dùng được NGAY HÔM NAY, trước khi hệ thống mới được viết:
chỉ cần ghi lại thời điểm và số token của vài lần chạy suy luận thủ công.

Chỉ dùng thư viện chuẩn.

Ví dụ:
    # Từ CSV job tự ghi
    python energy_per_token.py --db ../../server/telemetry.db --jobs jobs.csv

    # Từ bảng esg_events (khi hệ thống mới đã chạy)
    python energy_per_token.py --db ../../server/telemetry.db --from-events

    # So sánh A/B giữa hai chế độ scheduler
    python energy_per_token.py --db ../../server/telemetry.db --from-events --ab

Khuôn dạng jobs.csv:
    job_id,node,start_ts,end_ts,tokens_out,scheduler_mode
    j001,Node-A,1735689600.0,1735689604.8,187,thermal_aware
"""
import argparse
import csv
import json
import os
import sqlite3
import statistics
import sys

# Console Windows mặc định dùng codepage cp1252 -> in chữ tiếng Việt sẽ ném
# UnicodeEncodeError. Ép UTF-8 để người dùng không phải tự đặt PYTHONIOENCODING.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

MIN_SAMPLES_PER_JOB = 2      # cần ≥2 điểm mới tích phân được
MIN_JOBS_TO_SHOW = 20        # docs/07 §3.1 — dưới mức này không hiện % cải thiện
MIN_JOBS_CONFIDENT = 100


# ──────────────────────────────────────────────────────────────────────
# Đọc dữ liệu
# ──────────────────────────────────────────────────────────────────────

def open_ro(db_path):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_power_series(conn, node, t_from, t_to, pad_s=4.0):
    """Chuỗi (ts, power_w) của một node, đệm thêm hai đầu.

    Đệm để job ngắn hơn chu kỳ telemetry (2s) vẫn có điểm ở cả hai phía
    mà nội suy.
    """
    rows = conn.execute(
        "SELECT ts, power_w FROM telemetry "
        "WHERE node = ? AND ts >= ? AND ts <= ? AND power_w IS NOT NULL "
        "ORDER BY ts ASC",
        (node, t_from - pad_s, t_to + pad_s)).fetchall()
    return [(float(r["ts"]), float(r["power_w"])) for r in rows]


def load_jobs_csv(path):
    jobs = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                jobs.append({
                    "job_id": r["job_id"],
                    "node": r["node"],
                    "start_ts": float(r["start_ts"]),
                    "end_ts": float(r["end_ts"]),
                    "tokens_out": int(r["tokens_out"]),
                    "scheduler_mode": r.get("scheduler_mode", "unknown"),
                })
            except (KeyError, ValueError) as e:
                print(f"[WARN] Bỏ một dòng CSV không hợp lệ: {e}")
    return jobs


def load_jobs_events(conn):
    """Đọc job đã hoàn thành từ bảng esg_events (lược đồ ở docs/07 §6)."""
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "esg_events" not in tables:
        sys.exit("[ERR] Cơ sở dữ liệu chưa có bảng esg_events.\n"
                 "      Bảng này thuộc hệ thống mới (docs/07 §6) và chưa được "
                 "hiện thực.\n"
                 "      Hãy dùng --jobs <tệp.csv> thay thế.")
    jobs = []
    for r in conn.execute(
            "SELECT node, ts, detail FROM esg_events "
            "WHERE event = 'job_completed' ORDER BY ts ASC"):
        try:
            d = json.loads(r["detail"] or "{}")
            duration_s = float(d.get("duration_ms", 0)) / 1000.0
            jobs.append({
                "job_id": d.get("job_id", ""),
                "node": r["node"],
                "start_ts": float(r["ts"]) - duration_s,
                "end_ts": float(r["ts"]),
                "tokens_out": int(d.get("tokens_out", 0)),
                "scheduler_mode": d.get("scheduler_mode", "unknown"),
                # Nếu worker đã tự tính năng lượng thì tin số đó — nó đo ở
                # tần suất cao hơn nhiều so với telemetry 2 giây một lần.
                "energy_j_reported": d.get("energy_j"),
                "energy_source": d.get("energy_source", "none"),
            })
        except (ValueError, TypeError) as e:
            print(f"[WARN] Bỏ một sự kiện không đọc được: {e}")
    return jobs


# ──────────────────────────────────────────────────────────────────────
# Tích phân
# ──────────────────────────────────────────────────────────────────────

def integrate_trapezoid(series, t_from, t_to):
    """Tích phân công suất theo thời gian, đơn vị Joule.

    Nội suy tuyến tính tại hai biên để khoảng tích phân khớp đúng thời
    lượng job, không phải thời lượng giữa hai mẫu telemetry gần nhất.
    """
    if len(series) < MIN_SAMPLES_PER_JOB:
        return None
    pts = []
    for i, (t, p) in enumerate(series):
        if t_from <= t <= t_to:
            pts.append((t, p))
        elif t < t_from and i + 1 < len(series):
            t2, p2 = series[i + 1]
            if t2 > t_from and t2 > t:
                frac = (t_from - t) / (t2 - t)
                pts.append((t_from, p + (p2 - p) * frac))
        elif t > t_to and i > 0:
            t0, p0 = series[i - 1]
            if t0 < t_to and t > t0:
                frac = (t_to - t0) / (t - t0)
                pts.append((t_to, p0 + (p - p0) * frac))
            break
    pts = sorted(set(pts))
    if len(pts) < MIN_SAMPLES_PER_JOB:
        return None
    return sum((pts[i + 1][0] - pts[i][0]) * (pts[i + 1][1] + pts[i][1]) / 2.0
               for i in range(len(pts) - 1))


def compute(jobs, conn):
    """Gắn energy_j cho từng job. Trả về (đã_tính, bị_bỏ_qua)."""
    done, skipped = [], []
    for j in jobs:
        if j["tokens_out"] <= 0:
            skipped.append((j, "tokens_out = 0"))
            continue

        # Ưu tiên số worker tự đo — nó lấy mẫu dày hơn telemetry.
        if j.get("energy_j_reported") is not None and j.get("energy_source") == "sensor":
            j["energy_j"] = float(j["energy_j_reported"])
            j["energy_from"] = "worker"
        else:
            series = fetch_power_series(conn, j["node"], j["start_ts"], j["end_ts"])
            e = integrate_trapezoid(series, j["start_ts"], j["end_ts"])
            if e is None:
                skipped.append((j, f"không đủ mẫu công suất "
                                   f"({len(series)} điểm trong khoảng)"))
                continue
            j["energy_j"] = e
            j["energy_from"] = "telemetry"

        j["j_per_token"] = j["energy_j"] / j["tokens_out"]
        j["duration_s"] = j["end_ts"] - j["start_ts"]
        done.append(j)
    return done, skipped


def summarize(jobs, label):
    if not jobs:
        return None
    total_e = sum(j["energy_j"] for j in jobs)
    total_t = sum(j["tokens_out"] for j in jobs)
    per_job = [j["j_per_token"] for j in jobs]
    durations = sorted(j["duration_s"] for j in jobs)
    return {
        "label": label,
        "n_jobs": len(jobs),
        "total_energy_j": total_e,
        "total_tokens": total_t,
        # Tỷ số tổng/tổng, KHÔNG phải trung bình của các tỷ số: job dài phải
        # có trọng số lớn hơn, nếu không một job 5 token sẽ nặng ngang một
        # job 500 token.
        "j_per_token": total_e / total_t,
        "j_per_token_median_per_job": statistics.median(per_job),
        "latency_median_s": statistics.median(durations),
        "latency_p95_s": durations[max(0, int(len(durations) * 0.95) - 1)],
        "confidence": ("ok" if len(jobs) >= MIN_JOBS_CONFIDENT else
                       "sơ bộ" if len(jobs) >= MIN_JOBS_TO_SHOW else
                       "chưa đủ dữ liệu"),
    }


def print_summary(s):
    print(f"\n  {s['label']}")
    print(f"    Số job                {s['n_jobs']}")
    print(f"    Tổng năng lượng       {s['total_energy_j']:.1f} J")
    print(f"    Tổng token            {s['total_tokens']}")
    print(f"    J/token               {s['j_per_token']:.4f}")
    print(f"    J/token (trung vị)    {s['j_per_token_median_per_job']:.4f}")
    print(f"    Độ trễ trung vị       {s['latency_median_s']:.2f} s")
    print(f"    Độ trễ p95            {s['latency_p95_s']:.2f} s")
    print(f"    Độ tin cậy            {s['confidence']}")


# ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Tính J/token — ESG Tầng 1.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    p.add_argument("--db", required=True, help="đường dẫn telemetry.db")
    p.add_argument("--jobs", help="CSV danh sách job")
    p.add_argument("--from-events", action="store_true",
                   help="đọc job từ bảng esg_events")
    p.add_argument("--ab", action="store_true",
                   help="tách theo scheduler_mode và so sánh A/B")
    p.add_argument("--out", help="ghi kết quả ra JSON")
    args = p.parse_args()

    if not os.path.exists(args.db):
        sys.exit(f"Không tìm thấy cơ sở dữ liệu: {args.db}")
    if not args.jobs and not args.from_events:
        sys.exit("Cần một trong hai: --jobs <tệp.csv> hoặc --from-events")

    conn = open_ro(args.db)
    try:
        jobs = load_jobs_events(conn) if args.from_events else load_jobs_csv(args.jobs)
        print(f"[EPT] Nạp {len(jobs)} job")
        if not jobs:
            sys.exit("[EPT] Không có job nào để tính.")

        done, skipped = compute(jobs, conn)
    finally:
        conn.close()

    print(f"[EPT] Tính được {len(done)} job, bỏ qua {len(skipped)}")
    for j, why in skipped[:5]:
        print(f"       bỏ {j['job_id'] or '(không tên)'} @ {j['node']}: {why}")
    if len(skipped) > 5:
        print(f"       ... và {len(skipped) - 5} job khác")

    if not done:
        print("\n[EPT] Không tính được job nào. Nguyên nhân thường gặp:")
        print("  - Cột power_w trong telemetry toàn NULL "
              "→ chạy power_probe.ps1 để kiểm tra")
        print("  - Mốc thời gian job không khớp khoảng có telemetry")
        print("  - Agent không chạy trong lúc job diễn ra")
        sys.exit(1)

    result = {"overall": summarize(done, "TOÀN BỘ")}
    print("\n" + "=" * 60)
    print("  JOULE TRÊN TOKEN — ESG Tầng 1")
    print("=" * 60)
    print_summary(result["overall"])

    if args.ab:
        modes = {}
        for j in done:
            modes.setdefault(j["scheduler_mode"], []).append(j)
        result["by_mode"] = {m: summarize(js, m) for m, js in sorted(modes.items())}
        print("\n" + "-" * 60)
        print("  SO SÁNH A/B THEO CHẾ ĐỘ SCHEDULER")
        print("-" * 60)
        for s in result["by_mode"].values():
            print_summary(s)

        base = result["by_mode"].get("round_robin")
        ta = result["by_mode"].get("thermal_aware")
        if base and ta:
            imp = (base["j_per_token"] - ta["j_per_token"]) / base["j_per_token"] * 100
            result["improvement_pct"] = imp
            print("\n" + "-" * 60)
            if min(base["n_jobs"], ta["n_jobs"]) < MIN_JOBS_TO_SHOW:
                print(f"  Chênh lệch thô: {imp:+.1f}%")
                print(f"  CHƯA ĐỦ DỮ LIỆU để công bố (cần ≥{MIN_JOBS_TO_SHOW} job "
                      f"mỗi chế độ, hiện có {base['n_jobs']} và {ta['n_jobs']}).")
            elif imp > 0:
                print(f"  Điều phối theo nhiệt tiết kiệm hơn {imp:.1f}% "
                      f"năng lượng trên mỗi token.")
            else:
                print(f"  Điều phối theo nhiệt TỐN THÊM {-imp:.1f}% năng lượng "
                      f"trên mỗi token.")
                print(f"  Đây là kết quả hợp lệ và PHẢI được báo cáo đúng như vậy "
                      f"(docs/07 §3.2).")
                print(f"  Nó nói rằng ở quy mô này, lợi ích nằm ở tuổi thọ phần "
                      f"cứng và độ ổn định")
                print(f"  hiệu năng, không nằm ở hóa đơn điện.")
        elif args.ab:
            print("\n  Chưa đủ hai chế độ để so sánh. Chạy Host.exe --ab-benchmark "
                  "để sinh dữ liệu cả hai lượt.")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n[EPT] Đã ghi {args.out}")


if __name__ == "__main__":
    main()
