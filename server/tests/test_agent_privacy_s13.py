"""S13: mã agent không log nội dung prompt."""
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[2] / "agent"


def test_s13_agent_logs_prompt_len_never_prompt_text():
    prog = (AGENT_DIR / "Program.cs").read_text(encoding="utf-8")
    assert "prompt_len=" in prog
    assert "NEVER prompt" in prog or "Never log" in prog or "S13" in prog
    # Không có chỗ nối prompt vào Log(
    bad = False
    for line in prog.splitlines():
        if "Log(" in line and "prompt" in line.lower():
            if "prompt_len" in line or "never" in line.lower() or "S13" in line:
                continue
            if "prompt_len=" in line:
                continue
            # Allow comments
            if line.strip().startswith("//"):
                continue
            bad = True
            break
    assert not bad, "Tìm thấy Log(...) có thể ghi prompt"


def test_s13_llama_runner_uses_log_disable():
    src = (AGENT_DIR / "LlamaCppRunner.cs").read_text(encoding="utf-8")
    assert "--log-disable" in src
