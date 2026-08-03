# Thermal Orchestrator project overview

[Tiếng Việt](BÁO%20CÁO%20TỔNG%20QUAN%20DỰ%20ÁN.md) | English

## 1. Objective

Thermal Orchestrator is a proof of concept for distributing AI workload across
Windows machines according to real temperature and power data. Its goal is not
only to show a dashboard: it must collect real telemetry, forecast overheating
risk, select an appropriate node for LLM/compute jobs, and leave auditable
operational records.

## 2. Components

| Component | Technology | Responsibility |
|---|---|---|
| Host | Python, FastAPI, SQLite | Rooms, authentication, telemetry, scheduler, ESG, WebSocket, and tunnel. |
| NodeAgent | C#/.NET 8 | Sensors, outbound rejoin, job polling, and llama.cpp streaming. |
| LLM runtime | llama.cpp | Runs GGUF models on CPU and is owned by NodeAgent. |
| Dashboard | Single-file HTML/CSS/JS | Landing page, sign-in, cluster operations, chat, and configuration. |
| Bootstrapper | Single-file .NET EXE | Installs/updates the Host and Agent payload with UAC. |

## 3. Value flow

1. An admin creates a room and sets worker/admin passwords.
2. The Host starts its local NodeAgent; the Host computer becomes a real node
   after its first telemetry sample.
3. External workers use a setup link, enter the worker password, and join the
   Host through an outbound connection.
4. The Host forecasts temperature, excludes stale/not-ready nodes, and
   dispatches work to the best eligible node. If only one node is eligible, it
   continues processing the queue.
5. NodeAgent streams tokens from llama.cpp to the Host; the browser receives
   tokens over WebSocket and a final result associated with an attempt ID.

## 4. Technical invariants

- Workers are outbound-only; clients do not expose inbound listeners.
- Node identity comes from a token, never a node name in query/body data.
- Measured, inferred, and fallback ESG data are never combined.
- Chat runs only on a model/hash/generation/runtime that has reported READY.
- Passwords, tokens, prompts, and LLM answers are not written to audit/logs.
- One Host runs one local NodeAgent and one llama-server child of that agent.

## 5. Currently verified results

- Latest Host sensor check: CPU `40°C`, GPU `39°C`, CPU utilization `16%`,
  and power `23.3 W`.
- Python test suite: `351/351` passing.
- NodeAgent .NET test suite: `55/55` passing.
- The EXE update flow was validated through version `2026.08.03.7`: Host,
  Agent, and llama-server all belonged to the new version after update.
- The agent has a shared join backoff, preventing the telemetry and job loops
  from alternating `401/429` retries and taking a node offline.

## 6. PoC scope and limitations

The PoC supports a local Host, Windows workers, LAN operation, and Cloudflare
Tunnel. Quick Tunnel is suitable for demos; Named Tunnel requires a Cloudflare
token and hostname for stable acceptance testing. A real second worker,
Named Tunnel, and a long soak test require Internet access, Cloudflare
credentials, and another Windows machine.

Small CPU models such as Gemma 3B/E2B are appropriate for workflow and resource
testing. A 30B model can be used as a stress test, but it cannot prove that CPU
is sufficient for every workload: throughput and RAM use depend on available
memory, core count, and quantization.

## 7. Running the system

Full operating instructions are in [README.en.md](README.en.md). End users run
`ThermalOrchestrator.exe`, accept UAC, create a room, and wait for the Host
agent to become READY. A worker runs `NodeAgent.exe --setup <worker-link>`;
never copy a `localhost` URL to another computer.

## 8. Next steps

- Accept a Named Tunnel and a second physical worker.
- Smoke-test the full model catalog on target hardware.
- Run a four-hour soak test, including reconnect behavior and orphan-process
  checks.
- Code-sign the EXE and finish the enterprise release workflow.
