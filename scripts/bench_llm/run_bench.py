"""Harness benchmark LLM độc lập — G3, trước khi chốt ADR-005.

Không tích hợp vào agent/server. Chỉ đo và xuất số liệu.

Ví dụ:
    python scripts/bench_llm/run_bench.py --runtime llama --models all
    python scripts/bench_llm/run_bench.py --runtime all --models qwen25-05
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import zipfile
from pathlib import Path
import urllib.error
import urllib.request

# Console Windows cp1252 → ép UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from adapters.llama_server import LlamaServerAdapter  # noqa: E402
from adapters.onnx_genai import (  # noqa: E402
    OnnxGenAIAdapter, OnnxUnavailable, try_convert_model,
)
from monitor import (  # noqa: E402
    PeakMonitor, has_power_samples, machine_info,
    peak_temp_from_telemetry, run_energy_per_token, write_jobs_csv,
)
from report import (  # noqa: E402
    adr_table_rows, build_report_md, save_json, summarize_runs,
    write_vi_samples,
)
from sensor_bridge import SensorBridge  # noqa: E402

# Warmup riêng — không trùng prompts.json (tránh cache hit làm lệch median)
WARMUP_PROMPT = (
    "Warmup only. Reply with one word: OK. Do not reuse for scoring."
)
WARMUP_MAX_TOKENS = 8


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_sha256(path: Path, expected: str | None, label: str) -> None:
    if not expected:
        raise FileNotFoundError(
            f"Thiếu sha256 trong catalog cho {label} — từ chối chạy (D15).")
    got = sha256_file(path)
    if got.lower() != expected.lower():
        raise FileNotFoundError(
            f"SHA256 lệch ({label}): expected {expected}, got {got}")


def safe_extract_zip(zip_path: Path, dest_dir: Path) -> None:
    """Giải nén chống Zip Slip — chỉ ghi bên trong dest_dir."""
    dest_dir = dest_dir.resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or name.startswith("../") or "/../" in f"/{name}/":
                raise ValueError(f"Zip Slip bị chặn: {info.filename}")
            target = (dest_dir / name).resolve()
            if dest_dir != target and not str(target).startswith(
                    str(dest_dir) + os.sep):
                raise ValueError(f"Zip Slip bị chặn: {info.filename}")
        zf.extractall(dest_dir)

def _download(url: str, dest: Path) -> None:
    """Tải tệp với User-Agent; xóa phần dở nếu lỗi."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Thermal-PoC-bench_llm/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp, open(
            tmp, "wb",
        ) as out:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        tmp.replace(dest)
    except Exception:
        if tmp.is_file():
            tmp.unlink(missing_ok=True)
        raise


def ensure_llama_bin(catalog: dict, assets: Path) -> Path:
    """Tải + giải nén llama-server nếu chưa có; verify SHA256; trả exe."""
    meta = catalog["llama_cpp"]
    dest_dir = assets / f"llama-{meta['tag']}"
    exe = dest_dir / meta["exe_name"]
    impl = dest_dir / meta.get("impl_dll", "llama-server-impl.dll")
    zip_path = assets / meta["asset"]

    if not zip_path.is_file():
        print(f"[BENCH] Tải {meta['url']}")
        _download(meta["url"], zip_path)
    verify_sha256(zip_path, meta.get("zip_sha256"), meta["asset"])

    need_extract = not exe.is_file() or not impl.is_file()
    if need_extract:
        print(f"[BENCH] Giải nén an toàn {zip_path.name}")
        safe_extract_zip(zip_path, dest_dir)

    if not exe.is_file():
        found = list(dest_dir.rglob(meta["exe_name"]))
        if not found:
            raise FileNotFoundError(
                f"Không thấy {meta['exe_name']} sau khi giải nén")
        exe = found[0]
        impl_found = list(dest_dir.rglob(meta.get("impl_dll", "llama-server-impl.dll")))
        if impl_found:
            impl = impl_found[0]

    verify_sha256(exe, meta.get("exe_sha256"), meta["exe_name"])
    if impl.is_file() and meta.get("impl_dll_sha256"):
        verify_sha256(impl, meta["impl_dll_sha256"], impl.name)
    return exe


def ensure_gguf(model_meta: dict, assets: Path) -> Path:
    gg = model_meta["gguf"]
    path = assets / "gguf" / gg["filename"]
    path.parent.mkdir(parents=True, exist_ok=True)
    expected = gg.get("sha256")
    if path.is_file() and path.stat().st_size > 1_000_000:
        verify_sha256(path, expected, gg["filename"])
        return path
    print(f"[BENCH] Tải GGUF {gg['filename']}")
    try:
        _download(gg["url"], path)
    except urllib.error.HTTPError as e:
        raise FileNotFoundError(
            f"Tải GGUF thất bại HTTP {e.code}: {gg['url']}"
        ) from e
    verify_sha256(path, expected, gg["filename"])
    return path


def ensure_onnx_dir(
    model_id: str, model_meta: dict, assets: Path, convert: bool,
) -> Path | None:
    out = assets / "onnx" / model_id
    if (out / "genai_config.json").is_file():
        return out
    if not convert:
        return None
    hf_id = model_meta["onnx"]["hf_id"]
    precision = model_meta["onnx"].get("precision", "int4")
    print(f"[BENCH] Convert ONNX {hf_id} → {out}")
    try:
        return try_convert_model(hf_id, out, precision)
    except OnnxUnavailable as e:
        print(f"[BENCH] ONNX convert thất bại: {e}")
        return None


def pick_models(catalog: dict, arg: str) -> list[str]:
    all_ids = list(catalog["models"].keys())
    if arg.strip().lower() in ("all", "*"):
        return all_ids
    wanted = [x.strip() for x in arg.split(",") if x.strip()]
    bad = [x for x in wanted if x not in catalog["models"]]
    if bad:
        sys.exit(f"Mô hình không có trong catalog: {bad}. Có: {all_ids}")
    return wanted


def run_combo(
    *,
    runtime: str,
    model_id: str,
    model_meta: dict,
    prompts: list[dict],
    threads: int,
    assets: Path,
    outdir: Path,
    machine_id: str,
    telemetry_db: Path | None,
    node: str,
    convert_onnx: bool,
    llama_exe: Path | None,
) -> dict:
    """Chạy một tổ hợp runtime × model; trả về hàng tổng hợp."""
    print(f"\n[BENCH] === {runtime} × {model_id} ===")
    combo_dir = outdir / f"{runtime}_{model_id}"
    combo_dir.mkdir(parents=True, exist_ok=True)

    adapter = None
    na_reason = None
    cold_ms = None

    try:
        if runtime == "llama":
            assert llama_exe is not None
            gguf = ensure_gguf(model_meta, assets)
            adapter = LlamaServerAdapter(
                exe_path=llama_exe, model_path=gguf, threads=threads)
            cold_ms = adapter.start()
            print(f"[BENCH] Cold-start llama: {cold_ms:.0f} ms")
        else:
            onnx_dir = ensure_onnx_dir(
                model_id, model_meta, assets, convert_onnx)
            if onnx_dir is None:
                raise OnnxUnavailable(
                    "Chưa có mô hình ONNX. "
                    "Chạy với --convert-onnx hoặc đặt sẵn assets/onnx/<id>/")
            adapter = OnnxGenAIAdapter(onnx_dir, threads=threads)
            cold_ms = adapter.start()
            print(f"[BENCH] Cold-start onnx: {cold_ms:.0f} ms")
    except (
        OnnxUnavailable, FileNotFoundError, RuntimeError, TimeoutError,
        urllib.error.HTTPError, OSError,
    ) as e:
        na_reason = str(e)
        print(f"[BENCH] N/A: {na_reason}")
        return {
            "machine_id": machine_id,
            "runtime": runtime,
            "model_id": model_id,
            "model_display": model_meta["display"],
            "threads": threads,
            "status": "N/A",
            "na_reason": na_reason,
            "predict_tok_s_median": None,
            "prompt_tok_s_median": None,
            "peak_ram_mb": None,
            "peak_temp_c": None,
            "j_per_token": None,
            "j_per_token_note": f"N/A — {na_reason[:80]}",
            "cold_start_ms": None,
        }

    mon = PeakMonitor(pid=adapter.pid or os.getpid())
    mon.start()
    runs: list[dict] = []
    samples: list[dict] = []
    jobs: list[dict] = []
    window_start = time.time()

    try:
        # Warmup riêng — không trùng bộ 20 prompt (tránh cache hit skew)
        print("[BENCH] Warmup (prompt riêng, không ghi thống kê)")
        try:
            adapter.generate(WARMUP_PROMPT, WARMUP_MAX_TOKENS, temperature=0.0)
        except Exception as e:
            print(f"[BENCH] Warmup lỗi (tiếp tục): {e}")

        for i, p in enumerate(prompts):
            print(f"[BENCH] ({i+1}/{len(prompts)}) {p['id']}")
            try:
                r = adapter.generate(
                    p["prompt"], p.get("max_tokens", 128), temperature=0.0)
            except Exception as e:
                print(f"[BENCH] Lỗi generate: {e}")
                continue
            runs.append({
                "prompt_id": p["id"],
                "lang": p["lang"],
                "predict_tok_s": r.predict_tok_s,
                "prompt_tok_s": r.prompt_tok_s,
                "tokens_in": r.tokens_in,
                "tokens_out": r.tokens_out,
                "prompt_ms": r.prompt_ms,
                "predict_ms": r.predict_ms,
            })
            samples.append({
                "prompt_id": p["id"],
                "lang": p["lang"],
                "prompt": p["prompt"],
                "text": r.text,
                "tokens_out": r.tokens_out,
            })
            jobs.append({
                "job_id": f"{runtime}_{model_id}_{p['id']}",
                "node": node,
                "start_ts": r.start_ts,
                "end_ts": r.end_ts,
                "tokens_out": r.tokens_out,
                "scheduler_mode": "bench_g3",
            })
    finally:
        window_end = time.time()
        mon.stop()
        try:
            adapter.stop()
        except Exception:
            pass

    summary = summarize_runs(runs)
    peak_ram = mon.peak_rss_mb
    peak_temp = None
    if telemetry_db and telemetry_db.is_file():
        peak_temp = peak_temp_from_telemetry(
            str(telemetry_db), node, window_start, window_end)

    jobs_csv = combo_dir / "jobs.csv"
    write_jobs_csv(str(jobs_csv), jobs)

    j_per_token = None
    j_note = None
    ept_script = ROOT / "scripts" / "measure_power" / "energy_per_token.py"
    ept_out = combo_dir / "ept.json"
    if telemetry_db and telemetry_db.is_file() and jobs:
        if has_power_samples(
            str(telemetry_db), node, window_start, window_end,
        ):
            ept = run_energy_per_token(
                str(ept_script), str(telemetry_db),
                str(jobs_csv), str(ept_out),
            )
            if ept and ept.get("overall"):
                overall = ept["overall"]
                raw_j = overall.get("j_per_token")
                conf = overall.get("confidence") or ""
                n_jobs = overall.get("n_jobs")
                if conf == "chưa đủ dữ liệu":
                    j_per_token = None
                    j_note = (
                        f"chưa đủ dữ liệu (n={n_jobs}; raw≈"
                        f"{raw_j:.4f} — không công bố)"
                        if isinstance(raw_j, (int, float))
                        else f"chưa đủ dữ liệu (n={n_jobs})"
                    )
                elif conf == "sơ bộ":
                    j_per_token = raw_j
                    j_note = f"sơ bộ (n={n_jobs})"
                else:
                    j_per_token = raw_j
                    j_note = None
            elif ept and ept.get("error"):
                j_note = f"không đo được — {ept['error'][:60]}"
            else:
                j_note = "không đo được — EPT không trả overall"
        else:
            j_note = (
                "không đo được (thiếu sensor/power_w trong telemetry)"
            )
    else:
        j_note = (
            "không đo được (không có telemetry.db / agent không chạy)"
        )

    vi_path = write_vi_samples(
        outdir / "vi_samples" / runtime, model_id, samples, min_n=5)

    raw = {
        "runtime": runtime,
        "model_id": model_id,
        "cold_start_ms": cold_ms,
        "threads": threads,
        "peak_ram_mb": peak_ram,
        "peak_temp_c": peak_temp,
        "ram_method": mon.method,
        "summary": summary,
        "runs": runs,
        "samples": samples,
        "j_per_token": j_per_token,
        "j_per_token_note": j_note,
        "vi_samples_path": str(vi_path.relative_to(outdir)),
    }
    save_json(combo_dir / "raw.json", raw)

    row = {
        "machine_id": machine_id,
        "runtime": runtime,
        "model_id": model_id,
        "model_display": (
            f"{model_meta['display']} "
            + (
                model_meta.get("gguf", {}).get("quant", "Q4_K_M")
                if runtime == "llama"
                else model_meta.get("onnx", {}).get("precision", "int4").upper()
            )
        ),
        "threads": threads,
        "status": "ok",
        "predict_tok_s_median": summary["predict_tok_s_median"],
        "predict_tok_s_p95": summary["predict_tok_s_p95"],
        "prompt_tok_s_median": summary["prompt_tok_s_median"],
        "peak_ram_mb": peak_ram,
        "peak_temp_c": peak_temp,
        "j_per_token": j_per_token,
        "j_per_token_note": j_note,
        "cold_start_ms": cold_ms,
        "vi_samples_path": str(vi_path.relative_to(outdir)),
        "n_ok": summary["n"],
    }
    print(
        f"[BENCH] xong: tok/s sinh={row['predict_tok_s_median']}, "
        f"RAM={peak_ram:.0f} MB, temp={peak_temp}, J/tok={j_per_token or j_note}"
    )
    return row


def make_recommendation(rows: list[dict]) -> tuple[str, list[str]]:
    """Khuyến nghị dựa trên số liệu — không chấm VI tự động."""
    llama_ok = [
        r for r in rows
        if r.get("runtime") == "llama" and r.get("status") == "ok"
        and r.get("predict_tok_s_median")
    ]
    onnx_ok = [
        r for r in rows
        if r.get("runtime") == "onnx" and r.get("status") == "ok"
    ]

    # Ưu tiên qwen25-05 nếu có số liệu
    by_id = {r["model_id"]: r for r in llama_ok}
    base = by_id.get("qwen25-05") or (llama_ok[0] if llama_ok else None)

    if base is None:
        rec = (
            "Chưa đủ số liệu llama.cpp để khuyến nghị cấu hình khởi điểm. "
            "Ưu tiên sửa tải GGUF / binary rồi chạy lại trước khi chốt ADR."
        )
    else:
        tok = base["predict_tok_s_median"]
        rec = (
            f"Khuyến nghị khởi điểm (chưa chốt): **llama.cpp + "
            f"{base['model_display']}**, threads=nhân−2. "
            f"Trên máy này tok/s sinh median ≈ {tok:.1f}. "
            "Độ phủ GGUF cho phép đổi mô hình nhanh khi bạn đánh giá "
            "mẫu tiếng Việt. Giữ lớp trừu tượng ILlmRunner ở G4."
        )
        if "qwen25-15" in by_id:
            t15 = by_id["qwen25-15"]["predict_tok_s_median"]
            rec += (
                f" Qwen2.5-1.5B đạt ≈ {t15:.1f} tok/s trên cùng máy — "
                "cân nhắc nếu mẫu 0.5B tiếng Việt không đạt yêu cầu đọc."
            )

    flips = [
        "Mẫu tiếng Việt của 0.5B/0.6B không chấp nhận được khi bạn tự đọc "
        "→ chọn Qwen2.5-1.5B (đổi ngân sách RAM + thông lượng).",
        "Bộ phận IT chặn llama-server.exe và không whitelist "
        "→ chuyển ONNX Runtime GenAI (DLL ký số Microsoft).",
        "tok/s quá thấp trên máy yếu nhất trong cụm "
        "→ SmolLM2-360M hoặc hạ max_concurrent / cắt max_tokens.",
        "ONNX convert ổn định cho mọi mô hình chọn và IT không whitelist "
        "→ có thể chọn ONNX làm mặc định thay vì llama.cpp.",
    ]
    if not onnx_ok:
        flips.append(
            "ONNX chưa đo được trên máy này (thiếu mô hình/convert) — "
            "không dùng khoảng trống đó để loại ONNX."
        )
    return rec, flips


def main() -> None:
    p = argparse.ArgumentParser(description="Benchmark LLM G3 (độc lập)")
    p.add_argument(
        "--runtime", choices=["llama", "onnx", "all"], default="all")
    p.add_argument("--models", default="all",
                   help="danh sách id cách nhau bởi dấu phẩy, hoặc all")
    p.add_argument("--machine-id", default="",
                   help="nhãn máy; mặc định = hostname")
    p.add_argument(
        "--telemetry-db",
        default=str(ROOT / "server" / "telemetry.db"),
        help="đường dẫn telemetry.db (agent+server đang chạy để có J/token)",
    )
    p.add_argument("--node", default="",
                   help="tên node trong telemetry; mặc định = machine-id")
    p.add_argument("--outdir", default=str(HERE / "results"))
    p.add_argument("--assets", default=str(HERE / "assets"))
    p.add_argument(
        "--convert-onnx", action="store_true",
        help="thử convert ONNX INT4 nếu chưa có (chậm, cần GPU/CPU + HF)",
    )
    p.add_argument(
        "--skip-download", action="store_true",
        help="không tải llama/GGUF (phải có sẵn trong assets)",
    )
    p.add_argument(
        "--agent-exe",
        default=str(ROOT / "publish" / "NodeAgent" / "NodeAgent.exe"),
        help="NodeAgent.exe để lấy mẫu nhiệt/công suất cục bộ",
    )
    p.add_argument(
        "--no-sensor-bridge", action="store_true",
        help="không tự lấy mẫu cảm biến qua NodeAgent",
    )
    args = p.parse_args()

    catalog = load_json(HERE / "models.json")
    prompts = load_json(HERE / "prompts.json")
    outdir = Path(args.outdir)
    assets = Path(args.assets)
    outdir.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)

    info = machine_info()
    machine_id = args.machine_id or info["hostname"]
    node = args.node or machine_id
    threads = info["threads_used"]
    info["machine_id"] = machine_id
    save_json(outdir / "machine.json", info)
    print(
        f"[BENCH] Máy={machine_id} cores={info['cpu_count']} "
        f"threads={threads}"
    )

    model_ids = pick_models(catalog, args.models)
    runtimes = (
        ["llama", "onnx"] if args.runtime == "all" else [args.runtime]
    )

    llama_exe = None
    if "llama" in runtimes and not args.skip_download:
        llama_exe = ensure_llama_bin(catalog, assets)
    elif "llama" in runtimes:
        tag = catalog["llama_cpp"]["tag"]
        cand = list(
            (assets / f"llama-{tag}").rglob(
                catalog["llama_cpp"]["exe_name"]))
        if not cand:
            sys.exit("Không thấy llama-server.exe — bỏ --skip-download")
        llama_exe = cand[0]

    telemetry_db = Path(args.telemetry_db)
    bridge: SensorBridge | None = None
    agent_exe = Path(args.agent_exe)
    # Ưu tiên bridge cục bộ (không cần server) nếu có NodeAgent.
    if not args.no_sensor_bridge and agent_exe.is_file():
        local_db = outdir / "telemetry_bench.db"
        if local_db.is_file():
            local_db.unlink()
        bridge = SensorBridge(agent_exe, local_db, node=node, interval_s=3.0)
        bridge.start()
        telemetry_db = local_db
        print(
            f"[BENCH] Sensor bridge: {agent_exe.name} → {local_db.name} "
            f"(node={node})"
        )
        time.sleep(4.0)  # lấy ít nhất một mẫu trước khi suy luận
    elif not telemetry_db.is_file():
        print(
            f"[BENCH] Cảnh báo: không có {telemetry_db} và không có "
            "NodeAgent — J/token và nhiệt đỉnh sẽ là N/A."
        )
        telemetry_db = None

    rows: list[dict] = []
    try:
        for rt in runtimes:
            for mid in model_ids:
                row = run_combo(
                    runtime=rt,
                    model_id=mid,
                    model_meta=catalog["models"][mid],
                    prompts=prompts,
                    threads=threads,
                    assets=assets,
                    outdir=outdir,
                    machine_id=machine_id,
                    telemetry_db=telemetry_db,
                    node=node,
                    convert_onnx=args.convert_onnx,
                    llama_exe=llama_exe,
                )
                rows.append(row)
                save_json(
                    outdir / "summary.json",
                    {"rows": rows, "machine": info},
                )
    finally:
        if bridge is not None:
            bridge.stop()
            print(f"[BENCH] Sensor bridge dừng — {bridge.samples} mẫu")

    rec, flips = make_recommendation(rows)
    it_note = (
        "**NHẮC CHỦ DỰ ÁN:** Chưa thấy câu trả lời của bộ phận IT về việc "
        "whitelist một tệp `.exe` chưa ký số (`llama-server.exe`). "
        "Đây **có thể là yếu tố quyết định duy nhất** — hỏi IT trước khi "
        "chốt ADR-005. Nếu IT từ chối whitelist → chọn ONNX Runtime GenAI."
    )
    vi_paths = sorted({
        r["vi_samples_path"]
        for r in rows if r.get("vi_samples_path")
    })
    report = build_report_md(
        info, rows, vi_paths, rec, flips, it_note,
    )
    # Nhúng bảng ADR sẵn copy
    report += "\n## Dòng bảng sẵn dán vào ADR-005\n\n"
    report += adr_table_rows(rows) + "\n"

    (outdir / "REPORT.md").write_text(report, encoding="utf-8")
    save_json(outdir / "summary.json", {
        "machine": info,
        "rows": rows,
        "recommendation": rec,
        "flip_conditions": flips,
        "it_note": it_note,
    })
    print(f"\n[BENCH] Đã ghi {outdir / 'REPORT.md'}")
    print("[BENCH] ADR-005 vẫn ĐANG CHỜ QUYẾT ĐỊNH — bạn chốt, không phải agent.")


if __name__ == "__main__":
    main()
