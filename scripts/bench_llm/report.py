"""Gom kết quả benchmark → markdown / mẫu tiếng Việt.

Không tự chấm điểm chất lượng — chỉ in nguyên văn để người đọc.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path


def median(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None and x > 0]
    if not xs:
        return None
    return float(statistics.median(xs))


def p95(xs: list[float]) -> float | None:
    xs = sorted(x for x in xs if x is not None and x > 0)
    if not xs:
        return None
    idx = min(len(xs) - 1, int(round(0.95 * (len(xs) - 1))))
    return float(xs[idx])


def summarize_runs(runs: list[dict]) -> dict:
    pred = [r["predict_tok_s"] for r in runs]
    prompt = [r["prompt_tok_s"] for r in runs]
    return {
        "n": len(runs),
        "predict_tok_s_median": median(pred),
        "predict_tok_s_p95": p95(pred),
        "prompt_tok_s_median": median(prompt),
        "prompt_tok_s_p95": p95(prompt),
        "tokens_out_total": sum(r.get("tokens_out") or 0 for r in runs),
    }


def write_vi_samples(
    out_dir: Path, model_id: str, samples: list[dict], min_n: int = 5,
) -> Path:
    """Ghi ≥min_n cặp (prompt VI, trả lời) — không chấm điểm."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{model_id}.md"
    lines = [
        f"# Mẫu trả lời tiếng Việt — `{model_id}`",
        "",
        "> Agent **không** chấm điểm. Đọc và tự đánh giá.",
        "",
    ]
    count = 0
    for s in samples:
        if s.get("lang") not in ("vi", "mix"):
            continue
        count += 1
        lines.append(f"## {count}. `{s['prompt_id']}`")
        lines.append("")
        lines.append("**Prompt:**")
        lines.append("")
        lines.append("```")
        lines.append(s["prompt"])
        lines.append("```")
        lines.append("")
        lines.append("**Trả lời:**")
        lines.append("")
        lines.append("```")
        lines.append(s.get("text") or "(trống)")
        lines.append("```")
        lines.append("")
        if count >= min_n:
            # vẫn ghi thêm nếu còn
            pass
    if count < min_n:
        lines.append(
            f"> ⚠ Chỉ có {count}/{min_n} mẫu VI — kiểm tra prompts.json.")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def fmt_num(v, digits: int = 1) -> str:
    if v is None:
        return "N/A"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


def build_report_md(
    machine: dict,
    rows: list[dict],
    vi_paths: list[str],
    recommendation: str,
    flip_conditions: list[str],
    it_note: str,
) -> str:
    lines = [
        "# Báo cáo benchmark LLM — G3 (trước ADR-005)",
        "",
        "## Máy đo",
        "",
        f"- Hostname: `{machine.get('hostname')}`",
        f"- OS: {machine.get('os')}",
        f"- CPU: {machine.get('processor')}",
        f"- Số nhân logic: {machine.get('cpu_count')} "
        f"→ `--threads` = {machine.get('threads_used')} (nhân − 2)",
        f"- Thời điểm: {machine.get('measured_at')}",
        f"- **Hạn chế:** {machine.get('limitation')}",
        "",
        "## Bảng số liệu",
        "",
        "| Máy | Runtime | Mô hình | tok/s sinh "
        "(median) | tok/s prompt (median) | RAM đỉnh (MB) | "
        "Nhiệt đỉnh (°C) | J/token | Cold-start (ms) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            "| {machine} | {runtime} | {model} | {pred} | {prompt} | "
            "{ram} | {temp} | {jpt} | {cold} |".format(
                machine=r.get("machine_id", ""),
                runtime=r.get("runtime", ""),
                model=r.get("model_display", r.get("model_id", "")),
                pred=fmt_num(r.get("predict_tok_s_median")),
                prompt=fmt_num(r.get("prompt_tok_s_median")),
                ram=fmt_num(r.get("peak_ram_mb")),
                temp=fmt_num(r.get("peak_temp_c")),
                jpt=fmt_num(r.get("j_per_token"), 4)
                if r.get("j_per_token") is not None
                else (r.get("j_per_token_note") or "N/A"),
                cold=fmt_num(r.get("cold_start_ms"), 0),
            )
        )

    lines += [
        "",
        "## Mẫu tiếng Việt (để bạn đọc)",
        "",
    ]
    for p in vi_paths:
        lines.append(f"- `{p}`")

    lines += [
        "",
        "## Khuyến nghị của agent (chưa phải quyết định)",
        "",
        recommendation,
        "",
        "## Điều kiện lật ngược khuyến nghị",
        "",
    ]
    for c in flip_conditions:
        lines.append(f"- {c}")

    lines += [
        "",
        "## Nhắc IT (whitelist)",
        "",
        it_note,
        "",
        "## Trạng thái ADR",
        "",
        "ADR-005 vẫn **ĐANG CHỜ QUYẾT ĐỊNH**. "
        "Chủ dự án chốt sau khi đọc mẫu tiếng Việt và phản hồi IT.",
        "",
    ]
    return "\n".join(lines)


def adr_table_rows(rows: list[dict]) -> str:
    """Sinh các dòng markdown cho bảng ADR-005."""
    out = []
    for r in rows:
        jpt = r.get("j_per_token")
        if jpt is None:
            jpt_s = r.get("j_per_token_note") or "N/A"
        else:
            jpt_s = f"{jpt:.4f}"
        # Cột chất lượng VI: chỉ ghi "xem samples" — không tự chấm
        vi = "xem `results/vi_samples/` (chưa chấm)"
        out.append(
            f"| {r.get('machine_id', '')} | {r.get('runtime', '')} | "
            f"{r.get('model_display', '')} | "
            f"{fmt_num(r.get('predict_tok_s_median'))} | "
            f"{fmt_num(r.get('prompt_tok_s_median'))} | "
            f"{fmt_num(r.get('peak_ram_mb'))} | "
            f"{fmt_num(r.get('peak_temp_c'))} | "
            f"{jpt_s} | {vi} |"
        )
    return "\n".join(out)


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
