"""Adapter ONNX Runtime GenAI — chỉ chạy trên máy đo (Python OK).

Worker sản phẩm không cần Python; đây là công cụ đo độc lập.
Nếu thiếu package hoặc mô hình → trả N/A, không chặn toàn bộ G3.

API nhắm onnxruntime-genai ≥0.5 (Generator.append_tokens).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GenResult:
    text: str
    tokens_in: int
    tokens_out: int
    prompt_ms: float
    predict_ms: float
    prompt_tok_s: float
    predict_tok_s: float
    start_ts: float
    end_ts: float
    raw: dict


class OnnxUnavailable(Exception):
    """ONNX GenAI hoặc mô hình không sẵn sàng."""


class OnnxGenAIAdapter:
    def __init__(self, model_dir: Path, threads: int):
        self.model_dir = Path(model_dir)
        self.threads = threads
        self.model = None
        self.tokenizer = None
        self.cold_start_ms: float | None = None
        self._oga = None

    def start(self) -> float:
        try:
            import onnxruntime_genai as oga
        except ImportError as e:
            raise OnnxUnavailable(
                "Chưa cài onnxruntime-genai. "
                "pip install onnxruntime-genai"
            ) from e

        if not self.model_dir.is_dir():
            raise OnnxUnavailable(
                f"Không thấy thư mục mô hình ONNX: {self.model_dir}")

        cfg = self.model_dir / "genai_config.json"
        if not cfg.is_file():
            raise OnnxUnavailable(
                f"Thiếu genai_config.json trong {self.model_dir}. "
                "Tải gói ONNX GenAI sẵn hoặc convert bằng model builder."
            )

        # Khớp llama --threads = nhân−2: giới hạn thread trước khi load
        import os
        os.environ["OMP_NUM_THREADS"] = str(self.threads)
        os.environ["ORT_NUM_THREADS"] = str(self.threads)

        self._oga = oga
        t0 = time.perf_counter()
        self.model = oga.Model(str(self.model_dir))
        self.tokenizer = oga.Tokenizer(self.model)
        self.cold_start_ms = (time.perf_counter() - t0) * 1000.0
        return self.cold_start_ms

    def stop(self) -> None:
        self.model = None
        self.tokenizer = None

    @property
    def pid(self) -> int | None:
        import os
        return os.getpid()

    def _format_prompt(self, prompt: str) -> str:
        # Chat template Qwen-style nếu không có apply_chat_template
        try:
            if hasattr(self.tokenizer, "apply_chat_template"):
                return self.tokenizer.apply_chat_template(
                    [{"role": "user", "content": prompt}],
                    add_generation_prompt=True,
                )
        except Exception:
            pass
        return (
            f"<|im_start|>user\n{prompt}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )

    def generate(
        self, prompt: str, max_tokens: int, temperature: float = 0.0,
    ) -> GenResult:
        if self.model is None or self.tokenizer is None or self._oga is None:
            raise RuntimeError("ONNX adapter chưa start()")

        oga = self._oga
        formatted = self._format_prompt(prompt)

        start_ts = time.time()
        input_tokens = self.tokenizer.encode(formatted)
        # encode có thể trả numpy — chuẩn hóa list
        try:
            tokens_in = len(input_tokens)
        except TypeError:
            input_tokens = list(input_tokens)
            tokens_in = len(input_tokens)

        params = oga.GeneratorParams(self.model)
        search = {
            "max_length": tokens_in + max_tokens,
            "do_sample": False,
        }
        if temperature and temperature > 0:
            search["temperature"] = temperature
            search["do_sample"] = True
        try:
            params.set_search_options(**search)
        except TypeError:
            params.set_search_options(max_length=tokens_in + max_tokens)

        generator = oga.Generator(self.model, params)

        # Prefill = append_tokens only; decode = mọi generate_next_token
        # (khớp llama timings: prompt_per_second vs predicted_per_second)
        t_prefill0 = time.perf_counter()
        generator.append_tokens(input_tokens)
        prompt_ms = (time.perf_counter() - t_prefill0) * 1000.0

        out_ids: list[int] = []
        t_dec0 = time.perf_counter()
        while not generator.is_done() and len(out_ids) < max_tokens:
            generator.generate_next_token()
            nxt = generator.get_next_tokens()
            out_ids.append(int(nxt[0]))
        predict_ms = (time.perf_counter() - t_dec0) * 1000.0
        end_ts = time.time()

        tokens_out = len(out_ids)
        try:
            text = self.tokenizer.decode(out_ids)
        except Exception:
            text = self.tokenizer.decode(out_ids)

        predict_tok_s = (
            tokens_out / (predict_ms / 1000.0) if predict_ms > 0 else 0.0)
        prompt_tok_s = (
            tokens_in / (prompt_ms / 1000.0) if prompt_ms > 0 else 0.0)

        return GenResult(
            text=(text or "").strip(),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            prompt_ms=prompt_ms,
            predict_ms=predict_ms,
            prompt_tok_s=prompt_tok_s,
            predict_tok_s=predict_tok_s,
            start_ts=start_ts,
            end_ts=end_ts,
            raw={"threads": self.threads, "model_dir": str(self.model_dir),
                 "tok_s_definition": "decode_only_like_llama"},
        )


def try_convert_model(hf_id: str, out_dir: Path, precision: str = "int4") -> Path:
    """Convert mô hình HF → ONNX INT4 bằng model builder (máy dev)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    import subprocess
    import sys
    cmd = [
        sys.executable, "-m", "onnxruntime_genai.models.builder",
        "-m", hf_id,
        "-o", str(out_dir),
        "-p", precision,
        "-e", "cpu",
        "--extra_options", "int4_accuracy_level=4",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if proc.returncode != 0:
        raise OnnxUnavailable(
            f"Convert thất bại ({hf_id}): "
            f"{(proc.stderr or proc.stdout or '')[:400]}"
        )
    return out_dir
