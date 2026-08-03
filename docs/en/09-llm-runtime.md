# LLM runtime and model catalog

NodeAgent owns llama.cpp and reports its runtime identity to the Host. The
catalog supports selectable small models for CPU testing, including Qwen and
Gemma options. A model switch is atomic at the scheduling level: the Host
increments generation, lowers all readiness, and waits for matching reports.

Streaming uses worker-to-Host HTTP events and Host-to-browser WebSocket events.
This supports Cloudflare Tunnel WebSocket traffic and avoids creating a
server-side inference stub that could make an unavailable node look READY.

Small models are suitable for functional tests. Larger models are stress tests
whose memory and throughput requirements must be evaluated on target hardware.
