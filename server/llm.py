"""Host-side LLM inference (fallback P2 when no worker can take a chat job).

Default: HTTP to llama-server on 127.0.0.1 (ADR-005).
Tests / POC without a local runtime: stub echoes a short reply.
Thiếu usage → tokens null + tokens_estimated (không ước lượng char/4).
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

log = logging.getLogger("llm")

HOST_NODE = "__host__"


@dataclass
class LlmReply:
    text: str
    tokens_in: int | None
    tokens_out: int | None
    prompt_ms: float
    predict_ms: float
    tokens_estimated: bool = False


class HostLlm:
    """P2 host inference. ready() gates schedule_once(host_can_infer=...)."""

    def __init__(self, *, base_url: str | None = None,
                 stub: bool | None = None):
        if stub is None:
            # Default off — tests set POC_HOST_LLM_STUB=1
            stub = os.environ.get("POC_HOST_LLM_STUB", "0") == "1"
        self.stub = stub
        self.base_url = (base_url
                         or os.environ.get("POC_HOST_LLM_URL",
                                           "http://127.0.0.1:8080"))
        self._ready = stub  # stub always ready; real waits for ping
        self._enabled = True

    def set_ready(self, ready: bool):
        self._ready = bool(ready)

    def ready(self, cache=None, now=None) -> bool:
        return self._enabled and self._ready

    def generate(self, prompt: str, params: dict | None = None) -> LlmReply:
        params = params or {}
        max_tokens = int(params.get("max_tokens", 512))
        temperature = float(params.get("temperature", 0.7))
        if self.stub:
            # Do not echo the full prompt into logs — only lengths.
            text = (f"[host-stub] Đã nhận {len(prompt)} ký tự; "
                    f"max_tokens={max_tokens}.")
            return LlmReply(
                text=text,
                tokens_in=None,
                tokens_out=None,
                prompt_ms=1.0,
                predict_ms=5.0,
                tokens_estimated=True,
            )
        import urllib.request
        import json
        t0 = time.perf_counter()
        body = json.dumps({
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/v1/chat/completions",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        text = msg.get("content") or ""
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        tin = usage.get("prompt_tokens")
        tout = usage.get("completion_tokens")
        if tin is None or tout is None:
            return LlmReply(
                text=text,
                tokens_in=None,
                tokens_out=None,
                prompt_ms=elapsed_ms * 0.2,
                predict_ms=elapsed_ms * 0.8,
                tokens_estimated=True,
            )
        return LlmReply(
            text=text,
            tokens_in=int(tin),
            tokens_out=int(tout),
            prompt_ms=elapsed_ms * 0.2,
            predict_ms=elapsed_ms * 0.8,
            tokens_estimated=False,
        )
