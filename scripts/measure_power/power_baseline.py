"""Đo đường cong công suất của một máy: chạy tải bậc thang rồi ghi lại
(mức tải, nhiệt độ, công suất) ra CSV.

Đầu ra của script này là đầu vào của `power_model_fit.py`, script sẽ khớp
mô hình P(util, temp) dùng làm đường dự phòng khi cảm biến không báo công
suất, và trích hệ số dòng rò theo nhiệt cho ESG Tầng 2.

Chỉ dùng thư viện chuẩn — chạy được bằng Python hệ thống, không cần venv.

Quy trình đầy đủ: docs/08-do-cong-suat.md

Ví dụ:
    # Máy có cảm biến công suất, agent đang chạy và báo về server:
    python power_baseline.py --db ../../server/telemetry.db --node Node-A

    # Máy không có cảm biến — nhập số từ đồng hồ điện rời sau mỗi bậc:
    python power_baseline.py --db ../../server/telemetry.db --node Node-A --manual-power

    # Không sinh tải, chỉ trích xuất từ một phiên --calibrate đã chạy trước đó:
    python power_baseline.py --db ../../server/telemetry.db --node Node-A --extract-only
"""
import argparse
import csv
import math
import multiprocessing as mp
import os
import sqlite3
import sys
import time

# Console Windows mặc định dùng codepage cp1252 -> in chữ tiếng Việt sẽ ném
# UnicodeEncodeError. Ép UTF-8 để người dùng không phải tự đặt PYTHONIOENCODING.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# Bậc tải mặc định. Bậc 0 (nhàn rỗi) dài hơn để nhiệt độ kịp ổn định về nền.
DEFAULT_STEPS = [0, 25, 50, 75, 100]
DEFAULT_STEP_S = 120.0
IDLE_STEP_S = 180.0
SETTLE_FRACTION = 0.5   # chỉ lấy mẫu ở nửa sau mỗi bậc, khi nhiệt đã ổn định

CSV_COLUMNS = ["step_index", "target_util_pct", "ts", "cpu_temp", "gpu_temp",
               "cpu_util", "power_w", "power_source", "power_reading_ts",
               "phase"]


# ──────────────────────────────────────────────────────────────────────
# Sinh tải theo chu kỳ nhiệm vụ
# ──────────────────────────────────────────────────────────────────────

def _burn_worker(target_fraction, stop_at, slice_s=0.1):
    """Đốt CPU ở mức chiếm dụng xấp xỉ `target_fraction` của một nhân.

    Bận `target_fraction × slice_s` giây rồi ngủ phần còn lại. Trung bình
    trên nhiều lát cắt, mức sử dụng hội tụ về đúng tỷ lệ mong muốn.
    """
    if target_fraction <= 0:
        time.sleep(max(0.0, stop_at - time.time()))
        return
    busy_s = slice_s * target_fraction
    idle_s = slice_s - busy_s
    x = 1.0001
    while time.time() < stop_at:
        end_busy = time.time() + busy_s
        while time.time() < end_busy:
            # Vài trăm phép tính giữa hai lần đọc đồng hồ — đọc đồng hồ quá
            # dày sẽ khiến chính vòng lặp trở thành phần lớn tải.
            for _ in range(500):
                x = math.sqrt(x * 1.0001) + 0.0001
        if idle_s > 0:
            time.sleep(idle_s)


def run_load_step(target_util_pct, duration_s, workers):
    """Chạy một bậc tải, chặn cho tới khi hết thời gian."""
    if target_util_pct <= 0:
        time.sleep(duration_s)
        return
    stop_at = time.time() + duration_s
    fraction = min(target_util_pct / 100.0, 1.0)
    procs = [mp.Process(target=_burn_worker, args=(fraction, stop_at))
             for _ in range(workers)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()


# ──────────────────────────────────────────────────────────────────────
# Đọc telemetry
# ──────────────────────────────────────────────────────────────────────

def fetch_samples(db_path, node, t_from, t_to):
    """Lấy mẫu telemetry của một node trong khoảng thời gian.

    Dùng cùng lược đồ bảng với server/store.py — cố ý không import module đó
    để script chạy được độc lập, không cần cài phụ thuộc của server.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM telemetry WHERE node = ? AND ts >= ? AND ts <= ? "
            "ORDER BY ts ASC", (node, t_from, t_to)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def list_nodes(db_path):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return [r[0] for r in conn.execute("SELECT DISTINCT node FROM telemetry")]
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# Chạy chính
# ──────────────────────────────────────────────────────────────────────

def collect_baseline(args):
    steps = [int(s) for s in args.steps.split(",")]
    workers = args.workers or (os.cpu_count() or 4)
    rows = []
    manual_readings = {}

    print(f"[BASELINE] node={args.node}  bậc={steps}  worker={workers}")
    print(f"[BASELINE] cơ sở dữ liệu: {args.db}")
    print(f"[BASELINE] Tổng thời gian ước tính: "
          f"{sum(IDLE_STEP_S if s == 0 else args.step_seconds for s in steps) / 60:.0f} phút")
    print("[BASELINE] YÊU CẦU: agent phải đang chạy và báo telemetry về server.")
    print()

    for i, util in enumerate(steps):
        duration = IDLE_STEP_S if util == 0 else args.step_seconds
        t0 = time.time()
        print(f"[BASELINE] Bậc {i + 1}/{len(steps)}: tải {util:3d}%  "
              f"trong {duration:.0f}s ...", flush=True)

        settle_s = duration * SETTLE_FRACTION
        if args.manual_power and util > 0:
            # Nửa đầu ổn định nhiệt, hỏi watt khi tải vẫn chạy (nửa sau).
            run_load_step(util, settle_s, workers)
            raw = input(
                f"           Số trên đồng hồ điện ngay bây giờ (W), "
                f"Enter để bỏ qua: ").strip()
            if raw:
                try:
                    manual_readings[i] = (
                        float(raw.replace(",", ".")), time.time())
                except ValueError:
                    print("           Không đọc được số, bỏ qua bậc này.")
            remaining = duration - (time.time() - t0)
            if remaining > 0:
                run_load_step(util, remaining, workers)
        else:
            run_load_step(util, duration, workers)
        t1 = time.time()

        # Chỉ lấy nửa sau của bậc: nửa đầu là giai đoạn nhiệt còn đang lên.
        sample_from = t0 + duration * SETTLE_FRACTION
        samples = fetch_samples(args.db, args.node, sample_from, t1)
        if not samples:
            print(f"           CẢNH BÁO: không có mẫu telemetry nào trong "
                  f"khoảng này. Agent có đang chạy không?")

        manual = manual_readings.get(i)
        manual_w = manual[0] if manual else None
        manual_ts = manual[1] if manual else None
        if not samples and manual_w is not None:
            # Vẫn ghi một dòng manual nếu người dùng đã đo (không bịa khi bỏ qua).
            rows.append({
                "step_index": i,
                "target_util_pct": util,
                "ts": manual_ts or t1,
                "cpu_temp": None,
                "gpu_temp": None,
                "cpu_util": None,
                "power_w": manual_w,
                "power_source": "manual",
                "power_reading_ts": manual_ts,
                "phase": "load",
            })
        for s in samples:
            rows.append({
                "step_index": i,
                "target_util_pct": util,
                "ts": s["ts"],
                "cpu_temp": s.get("cpu_temp"),
                "gpu_temp": s.get("gpu_temp"),
                "cpu_util": s.get("cpu_util"),
                "power_w": (manual_w if manual_w is not None
                            else s.get("power_w")),
                "power_source": ("manual" if manual_w is not None
                                 else ("sensor" if s.get("power_w") is not None
                                       else "none")),
                "power_reading_ts": manual_ts,
                "phase": "load",
            })
        temps = [s["cpu_temp"] for s in samples if s.get("cpu_temp") is not None]
        if temps:
            print(f"           {len(samples)} mẫu, nhiệt trung bình "
                  f"{sum(temps) / len(temps):.1f}°C")

    return rows


def extract_only(args):
    """Trích toàn bộ telemetry đã có, không sinh tải.

    Dùng khi đã chạy `server.py --calibrate` trước đó — phiên hiệu chuẩn đã
    tạo ra đúng loại dữ liệu cần thiết (chu kỳ nhàn rỗi/nhẹ/nặng/nguội).
    """
    print(f"[EXTRACT] Trích toàn bộ telemetry của {args.node} từ {args.db}")
    samples = fetch_samples(args.db, args.node, 0, time.time() + 1)
    print(f"[EXTRACT] {len(samples)} mẫu")
    return [{
        "step_index": -1,
        "target_util_pct": "",
        "ts": s["ts"],
        "cpu_temp": s.get("cpu_temp"),
        "gpu_temp": s.get("gpu_temp"),
        "cpu_util": s.get("cpu_util"),
        "power_w": s.get("power_w"),
        "power_source": "sensor" if s.get("power_w") is not None else "none",
        "power_reading_ts": None,
        "phase": "extracted",
    } for s in samples]


def write_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"\n[BASELINE] Đã ghi {len(rows)} dòng vào {path}")

    with_power = sum(1 for r in rows if r["power_w"] is not None and r["power_w"] != "")
    print(f"[BASELINE] Trong đó {with_power} dòng có số công suất "
          f"({with_power * 100 // max(len(rows), 1)}%)")
    if with_power == 0:
        print("[BASELINE] CẢNH BÁO: không có dòng nào có công suất. "
              "Không khớp được mô hình.")
        print("[BASELINE] Chạy lại với --manual-power và một đồng hồ điện rời, "
              "hoặc xem docs/08-do-cong-suat.md §5.")
    else:
        print(f"[BASELINE] Bước tiếp theo: python power_model_fit.py --csv {path}")


def main():
    p = argparse.ArgumentParser(
        description="Đo đường cong công suất bằng tải bậc thang.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    p.add_argument("--db", required=True,
                   help="đường dẫn telemetry.db (thường là server/telemetry.db)")
    p.add_argument("--node", help="tên node cần đo; bỏ trống để liệt kê các node có sẵn")
    p.add_argument("--out", default="power_baseline.csv", help="tệp CSV đầu ra")
    p.add_argument("--steps", default=",".join(str(s) for s in DEFAULT_STEPS),
                   help="các mức tải phần trăm, phân tách bằng dấu phẩy")
    p.add_argument("--step-seconds", type=float, default=DEFAULT_STEP_S,
                   help="thời lượng mỗi bậc (giây)")
    p.add_argument("--workers", type=int, default=0,
                   help="số tiến trình đốt CPU (mặc định = số nhân)")
    p.add_argument("--manual-power", action="store_true",
                   help="hỏi số công suất từ đồng hồ điện rời sau mỗi bậc")
    p.add_argument("--extract-only", action="store_true",
                   help="không sinh tải, chỉ trích telemetry đã có")
    args = p.parse_args()

    if not os.path.exists(args.db):
        sys.exit(f"Không tìm thấy cơ sở dữ liệu: {args.db}\n"
                 f"Server đã chạy lần nào chưa? telemetry.db được tạo khi "
                 f"server.py khởi động.")

    nodes = list_nodes(args.db)
    if not args.node:
        print("Các node có trong cơ sở dữ liệu:")
        for n in nodes:
            print(f"  - {n}")
        sys.exit("\nChạy lại với --node <tên>")
    if args.node not in nodes:
        sys.exit(f"Không có node '{args.node}'. Các node có sẵn: {nodes}")

    rows = extract_only(args) if args.extract_only else collect_baseline(args)
    write_csv(rows, args.out)


if __name__ == "__main__":
    mp.freeze_support()   # cần trên Windows khi đóng gói
    main()
