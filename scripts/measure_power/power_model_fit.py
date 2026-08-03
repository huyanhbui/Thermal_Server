"""Khớp mô hình công suất P(util, temp) từ CSV do power_baseline.py sinh ra.

Mô hình:   P = a + b·util + c·temp

    a  công suất nền (W) — máy nhàn rỗi, nhiệt tham chiếu
    b  công suất trên mỗi phần trăm sử dụng CPU (W/%)
    c  công suất tăng thêm trên mỗi °C — ĐÂY LÀ HỆ SỐ DÒNG RÒ,
       dùng cho ESG Tầng 2 (docs/07-esg-3-tang.md §4.1)

Kết quả ghi ra `power_model.json` với hai công dụng:

  1. Đường dự phòng: ước lượng công suất cho máy không có cảm biến.
     Job dùng đường này được đánh dấu power_source='model' và đi vào
     ESG Tầng 2, KHÔNG vào Tầng 1.
  2. p_idle / p_max cho thành phần `efficiency` của công thức chấm điểm
     (docs/04-dac-ta-scheduler.md §4.4).

Chỉ dùng thư viện chuẩn. Bình phương tối thiểu giải bằng hệ phương trình
chuẩn 3×3 với khử Gauss — không cần numpy.

Ví dụ:
    python power_model_fit.py --csv power_baseline.csv
    python power_model_fit.py --csv power_baseline.csv --out ../../server/power_model.json
"""
import argparse
import csv
import json
import os
import statistics
import sys
import time

# Console Windows mặc định dùng codepage cp1252 -> in chữ tiếng Việt sẽ ném
# UnicodeEncodeError. Ép UTF-8 để người dùng không phải tự đặt PYTHONIOENCODING.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

MIN_ROWS = 30
MIN_TEMP_SPREAD_C = 8.0      # dưới mức này thì hệ số nhiệt không đáng tin
MIN_UTIL_SPREAD_PCT = 30.0


# ──────────────────────────────────────────────────────────────────────
# Đại số tuyến tính tối thiểu
# ──────────────────────────────────────────────────────────────────────

def solve_3x3(A, y):
    """Giải hệ 3×3 bằng khử Gauss có chọn phần tử trụ. Trả None nếu suy biến."""
    m = [row[:] + [y[i]] for i, row in enumerate(A)]
    n = 3
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            return None
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(n):
            if r == col:
                continue
            factor = m[r][col] / m[col][col]
            for c in range(col, n + 1):
                m[r][c] -= factor * m[col][c]
    return [m[i][n] / m[i][i] for i in range(n)]


def fit_linear(rows, use_temp=True):
    """Bình phương tối thiểu cho P = a + b·util (+ c·temp).

    Trả về (hệ_số, chỉ_số_chất_lượng).
    """
    n = len(rows)
    # Ma trận thiết kế: cột hằng, cột util, cột temp (hoặc hằng 0 khi bỏ nhiệt)
    xs = [(1.0, r["util"], r["temp"] if use_temp else 0.0) for r in rows]
    ys = [r["power"] for r in rows]

    # Hệ phương trình chuẩn: (XᵀX)β = Xᵀy
    A = [[sum(xs[k][i] * xs[k][j] for k in range(n)) for j in range(3)]
         for i in range(3)]
    b = [sum(xs[k][i] * ys[k] for k in range(n)) for i in range(3)]

    if not use_temp:
        # Cột nhiệt toàn 0 khiến ma trận suy biến — ghim c = 0.
        A[2] = [0.0, 0.0, 1.0]
        b[2] = 0.0

    beta = solve_3x3(A, b)
    if beta is None:
        return None, None

    pred = [beta[0] + beta[1] * r["util"] + beta[2] * (r["temp"] if use_temp else 0.0)
            for r in rows]
    residuals = [ys[k] - pred[k] for k in range(n)]
    mean_y = sum(ys) / n
    ss_res = sum(e * e for e in residuals)
    ss_tot = sum((v - mean_y) ** 2 for v in ys)

    quality = {
        "r_squared": (1.0 - ss_res / ss_tot) if ss_tot > 1e-12 else 0.0,
        "mae_w": sum(abs(e) for e in residuals) / n,
        "rmse_w": (ss_res / n) ** 0.5,
        "n_rows": n,
    }
    return beta, quality


# ──────────────────────────────────────────────────────────────────────
# Nạp và làm sạch dữ liệu
# ──────────────────────────────────────────────────────────────────────

def load_rows(path):
    """Đọc CSV, giữ lại các dòng có đủ (util, temp, power)."""
    kept, skipped = [], 0
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                util = float(r["cpu_util"])
                temp = float(r["cpu_temp"])
                power = float(r["power_w"])
            except (TypeError, ValueError, KeyError):
                skipped += 1
                continue
            if not (0.0 <= util <= 100.0) or not (0.0 < temp < 130.0) or power <= 0:
                skipped += 1     # giá trị phi lý — cảm biến lỗi hoặc nhập nhầm
                continue
            kept.append({"util": util, "temp": temp, "power": power})
    return kept, skipped


def strip_outliers(rows, sigma=3.0):
    """Bỏ các điểm công suất lệch quá `sigma` độ lệch chuẩn.

    Cảm biến thỉnh thoảng trả một giá trị vọt bất thường; một điểm như vậy
    kéo cả đường hồi quy đi rất xa.
    """
    if len(rows) < 10:
        return rows, 0
    powers = [r["power"] for r in rows]
    mu = statistics.mean(powers)
    sd = statistics.pstdev(powers)
    if sd < 1e-9:
        return rows, 0
    kept = [r for r in rows if abs(r["power"] - mu) <= sigma * sd]
    return kept, len(rows) - len(kept)


# ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Khớp mô hình P(util, temp) từ CSV đo công suất.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    p.add_argument("--csv", required=True, help="CSV từ power_baseline.py")
    p.add_argument("--out", default="power_model.json", help="tệp JSON đầu ra")
    p.add_argument("--node", default="", help="tên node, ghi vào metadata")
    p.add_argument("--no-temp", action="store_true",
                   help="bỏ số hạng nhiệt (dùng khi dữ liệu nhiệt quá hẹp)")
    args = p.parse_args()

    if not os.path.exists(args.csv):
        sys.exit(f"Không tìm thấy tệp: {args.csv}")

    rows, skipped = load_rows(args.csv)
    print(f"[FIT] Đọc {len(rows)} dòng dùng được, bỏ {skipped} dòng thiếu dữ liệu")

    if len(rows) < MIN_ROWS:
        sys.exit(f"[FIT] Không đủ dữ liệu (<{MIN_ROWS} dòng có cả util, temp và "
                 f"power).\n"
                 f"      Máy này có đọc được công suất không? Chạy "
                 f"power_probe.ps1 để kiểm tra,\n"
                 f"      hoặc chạy lại power_baseline.py với --manual-power.")

    rows, dropped = strip_outliers(rows)
    if dropped:
        print(f"[FIT] Loại {dropped} điểm bất thường (lệch >3σ)")

    util_spread = max(r["util"] for r in rows) - min(r["util"] for r in rows)
    temp_spread = max(r["temp"] for r in rows) - min(r["temp"] for r in rows)
    print(f"[FIT] Dải sử dụng CPU: {util_spread:.0f}%   dải nhiệt: {temp_spread:.1f}°C")

    warnings = []
    if util_spread < MIN_UTIL_SPREAD_PCT:
        warnings.append(
            f"Dải sử dụng CPU chỉ {util_spread:.0f}% (<{MIN_UTIL_SPREAD_PCT:.0f}%). "
            f"Hệ số b không đáng tin — cần chạy đủ các bậc từ nhàn rỗi tới 100%.")

    use_temp = not args.no_temp
    if use_temp and temp_spread < MIN_TEMP_SPREAD_C:
        warnings.append(
            f"Dải nhiệt chỉ {temp_spread:.1f}°C (<{MIN_TEMP_SPREAD_C:.0f}°C). "
            f"Bỏ số hạng nhiệt — hệ số dòng rò sẽ KHÔNG khả dụng cho ESG Tầng 2.")
        use_temp = False

    beta, quality = fit_linear(rows, use_temp=use_temp)
    if beta is None:
        sys.exit("[FIT] Ma trận suy biến — dữ liệu không đủ đa dạng để khớp.")

    a, b, c = beta
    print()
    print(f"[FIT] P = {a:.2f} + {b:.4f}·util" + (f" + {c:.4f}·temp" if use_temp else ""))
    print(f"[FIT] R² = {quality['r_squared']:.3f}   "
          f"MAE = {quality['mae_w']:.2f} W   RMSE = {quality['rmse_w']:.2f} W")

    if quality["r_squared"] < 0.7:
        warnings.append(
            f"R² = {quality['r_squared']:.2f} là thấp. Mô hình tuyến tính không mô tả "
            f"tốt máy này; dùng ước lượng công suất từ đây sẽ có sai số lớn.")

    # p_idle / p_max cho thành phần `efficiency` của scheduler.
    temps = [r["temp"] for r in rows]
    t_ref = statistics.median(temps)
    p_idle = a + b * 0.0 + (c * min(temps) if use_temp else 0.0)
    p_max = a + b * 100.0 + (c * max(temps) if use_temp else 0.0)
    print(f"[FIT] p_idle ≈ {p_idle:.1f} W   p_max ≈ {p_max:.1f} W")

    # Hệ số dòng rò cho ESG Tầng 2: phần trăm công suất tăng thêm trên mỗi °C,
    # quy chiếu về điểm vận hành 50% tải.
    leakage_pct_per_c = None
    if use_temp:
        p_ref = a + b * 50.0 + c * t_ref
        if p_ref > 0:
            leakage_pct_per_c = (c / p_ref) * 100.0
            print(f"[FIT] Hệ số dòng rò: {c:.4f} W/°C "
                  f"= {leakage_pct_per_c:.3f}% công suất trên mỗi °C")
            if not (0.1 <= leakage_pct_per_c <= 1.5):
                warnings.append(
                    f"Hệ số dòng rò {leakage_pct_per_c:.3f}%/°C nằm ngoài khoảng "
                    f"điển hình 0,3–0,6%/°C. Nhiều khả năng phép hồi quy bị nhiễu "
                    f"chứ không phải phần cứng đặc biệt — kiểm tra lại dữ liệu "
                    f"trước khi dùng cho báo cáo ESG.")

    model = {
        "_comment": "Sinh bởi power_model_fit.py — xem docs/08-do-cong-suat.md",
        "node": args.node,
        "fitted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source_csv": os.path.basename(args.csv),
        "formula": "P = a + b*util" + (" + c*temp" if use_temp else ""),
        "coefficients": {"a": round(a, 4), "b": round(b, 6),
                         "c": round(c, 6) if use_temp else 0.0},
        "temp_term_used": use_temp,
        "p_idle_w": round(p_idle, 2),
        "p_max_w": round(p_max, 2),
        "leakage_w_per_c": round(c, 6) if use_temp else None,
        "leakage_pct_per_c": (round(leakage_pct_per_c, 4)
                              if leakage_pct_per_c is not None else None),
        "quality": {k: round(v, 4) if isinstance(v, float) else v
                    for k, v in quality.items()},
        "data_range": {
            "util_min": round(min(r["util"] for r in rows), 1),
            "util_max": round(max(r["util"] for r in rows), 1),
            "temp_min": round(min(temps), 1),
            "temp_max": round(max(temps), 1),
        },
        "warnings": warnings,
        "usage_note": ("Công suất ước lượng từ mô hình này phải được đánh dấu "
                       "power_source='model' và CHỈ được dùng ở ESG Tầng 2. "
                       "Không bao giờ trộn vào phép tính J/token của Tầng 1."),
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(model, f, ensure_ascii=False, indent=2)

    print(f"\n[FIT] Đã ghi {args.out}")
    if warnings:
        print("\n[FIT] CẢNH BÁO:")
        for w in warnings:
            print(f"  - {w}")
    else:
        print("[FIT] Không có cảnh báo — mô hình dùng được.")


if __name__ == "__main__":
    main()
