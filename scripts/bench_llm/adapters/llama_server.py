"""Adapter llama-server: spawn tiến trình con, gọi HTTP, đọc timings.

Dùng API /v1/chat/completions (áp chat template của mô hình Instruct).
Thống kê token lấy từ trường timings — không tokenize lại đầu ra.
"""
from __future__ import annotations

import json
import socket
import subprocess
import time
import urllib.error
import urllib.request
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


class LlamaServerAdapter:
    def __init__(
        self,
        exe_path: Path,
        model_path: Path,
        threads: int,
        host: str = "127.0.0.1",
        port: int | None = None,
        ctx_size: int = 4096,
    ):
        self.exe_path = Path(exe_path)
        self.model_path = Path(model_path)
        self.threads = threads
        self.host = host
        self.port = port or _free_port()
        self.ctx_size = ctx_size
        self.proc: subprocess.Popen | None = None
        self.cold_start_ms: float | None = None
        self.base = f"http://{self.host}:{self.port}"

    def start(self) -> float:
        """Khởi động lạnh; trả về thời gian ms tới khi /health OK."""
        if not self.exe_path.is_file():
            raise FileNotFoundError(f"Không thấy {self.exe_path}")
        if not self.model_path.is_file():
            raise FileNotFoundError(f"Không thấy {self.model_path}")

        cmd = [
            str(self.exe_path),
            "-m", str(self.model_path),
            "--host", self.host,
            "--port", str(self.port),
            "--threads", str(self.threads),
            "-c", str(self.ctx_size),
            "--parallel", "1",
        ]
        t0 = time.perf_counter()
        self.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(self.exe_path.parent),
        )
        deadline = time.time() + 180.0
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(
                    f"llama-server thoát sớm, code={self.proc.returncode}")
            if _http_ok(f"{self.base}/health"):
                self.cold_start_ms = (time.perf_counter() - t0) * 1000.0
                return self.cold_start_ms
            time.sleep(0.25)
        self.stop()
        raise TimeoutError("llama-server không sẵn sàng trong 180s")

    def stop(self) -> None:
        if self.proc is None:
            return
        try:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
        except OSError:
            pass
        self.proc = None

    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.proc else None

    def generate(
        self, prompt: str, max_tokens: int, temperature: float = 0.0,
    ) -> GenResult:
        body = {
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            # Qwen3: tắt "thinking" để content không rỗng / không chỉ nằm
            # trong reasoning_content (nếu server/template hỗ trợ).
            "chat_template_kwargs": {"enable_thinking": False},
        }
        start_ts = time.time()
        data = _post_json(f"{self.base}/v1/chat/completions", body)
        end_ts = time.time()

        text = ""
        choices = data.get("choices") or []
        if choices:
            msg = choices[0].get("message") or {}
            content = msg.get("content")
            reasoning = msg.get("reasoning_content")
            # Phân biệt None vs "" — không fallback thinking khi content=""
            if isinstance(content, str) and content.strip():
                text = content
            elif isinstance(reasoning, str) and reasoning.strip():
                text = reasoning
            elif content is not None:
                text = content
            else:
                text = choices[0].get("text") or ""

        timings = data.get("timings") or {}
        usage = data.get("usage") or {}

        tokens_out = int(
            timings.get("predicted_n")
            or usage.get("completion_tokens")
            or 0)
        tokens_in = int(
            timings.get("prompt_n")
            or usage.get("prompt_tokens")
            or 0)
        prompt_ms = float(timings.get("prompt_ms") or 0.0)
        predict_ms = float(timings.get("predicted_ms") or 0.0)
        prompt_tok_s = float(timings.get("prompt_per_second") or 0.0)
        predict_tok_s = float(timings.get("predicted_per_second") or 0.0)

        # Fallback nếu thiếu timings (phiên bản lạ)
        if predict_tok_s <= 0 and predict_ms > 0 and tokens_out > 0:
            predict_tok_s = tokens_out / (predict_ms / 1000.0)
        if prompt_tok_s <= 0 and prompt_ms > 0 and tokens_in > 0:
            prompt_tok_s = tokens_in / (prompt_ms / 1000.0)

        return GenResult(
            text=text.strip(),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            prompt_ms=prompt_ms,
            predict_ms=predict_ms,
            prompt_tok_s=prompt_tok_s,
            predict_tok_s=predict_tok_s,
            start_ts=start_ts,
            end_ts=end_ts,
            raw=data,
        )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _post_json(url: str, body: dict) -> dict:
    raw = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read().decode("utf-8"))
