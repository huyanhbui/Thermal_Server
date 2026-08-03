# How Thermal Orchestrator works

[Tiếng Việt](HOW_IT_WORKS.md) | English

## Architecture

```text
Admin browser ── WebSocket / HTTP ──► Host (FastAPI + SQLite)
                                      │
                         forecasting + scheduler + audit
                                      │
                ┌─────────────────────┼─────────────────────┐
                ▼                     ▼                     ▼
          Host NodeAgent         Worker A NodeAgent    Worker B NodeAgent
          telemetry + LLM        telemetry + LLM       telemetry + LLM
                │                     │                     │
                └──── outbound HTTP ──┴──── outbound HTTP ──┘
```

The Host never opens a connection to a worker. Every NodeAgent sends telemetry, long-polls for work, and posts results/chat chunks to the Host. Therefore a worker needs no inbound listener, NAT rule, or port forwarding.

## Host lifecycle

1. `ThermalOrchestrator.exe` requests UAC, extracts the payload to `%ProgramData%\ThermalOrchestrator\versions\<version>`, and starts the Host on port 8000.
2. The user creates or restores a room. Password verifiers and salts reside in SQLite; session tokens live only in memory.
3. The Host provisions the local NodeAgent configuration using DPAPI and starts the agent.
4. The agent joins as a normal worker. The Host shows the node only after its first telemetry sample.
5. NodeAgent owns `llama-server` through a Job Object. When the agent stops, its child runtime stops too; there is no second Host LLM runtime.

Visible local-agent states are `missing`, `starting`, `awaiting_uac`, `joining`, `downloading_model`, `ready`, and `error`.

## Telemetry, forecasting, and scheduling

Every two seconds the agent reads CPU temperature, GPU temperature, CPU utilization, and package power through `SensorReader.cs`, then posts `/ingest`. The Host writes the sample to SQLite, builds a feature window, and forecasts the maximum temperature over the next three minutes.

The scheduler prefers cooler and less busy nodes, but does not leave a queue idle when only one machine is available. One READY node receives the next job as soon as it finishes the previous one; with multiple nodes, parallel jobs are allocated before reusing a node. A stale node or an LLM runtime that is not READY cannot receive LLM chat work.

## Scheduling non-LLM work

The queue is not limited to chat. The Host also schedules ordinary compute tasks, for example `burn` jobs used for CPU load tests, thermal calibration, or a declared background workload. Each job has a type, duration, core count, and deadline; the agent receives it through `GET /jobs/next`, runs `JobRunner`, and posts its result to the Host.

For these jobs, the scheduler uses predicted temperature, thermal headroom, busy state, and recent telemetry to select a machine. A hot, stale, or fully-occupied node does not get more work. If only one suitable machine remains, the Host keeps assigning it sequential jobs instead of pausing the entire workload. LLM jobs add the runtime READY requirement; ordinary compute jobs do not depend on an LLM model.

## LLM and streaming

A node is LLM READY only when it reports the selected model's exact `model_id`, SHA-256, `generation`, and `runtime_id`. On a model change, the Host increments the generation and lowers readiness for every node. New chat is accepted only after a node reports the new generation. If no eligible node exists, `/chat` returns `NO_LLM_READY` rather than creating a stuck job.

NodeAgent consumes the real llama.cpp stream and posts deltas to `/jobs/{job_id}/events`; the Host emits `chat_token` through WebSocket. The final result is idempotent by `job_id + attempt_id`. If a node fails during inference, the scheduler tries the next suitable node once and avoids the failed node when another choice exists.

## Tunnel and worker machines

Quick Tunnel creates a random URL; Named Tunnel uses a stable hostname and token. The Host exposes a worker invite link only after the public HTTPS probe succeeds. A worker link goes to `/worker-setup?code=...`, grants no admin token, and never contains a password.

On a worker, run:

```powershell
.\NodeAgent.exe --setup "https://host.example/worker-setup?code=THERMAL-XXXX"
```

The wizard asks for node name, Host URL, and worker password. It rejects `localhost` on another machine, preventing a worker from connecting to itself.

## ESG data

ESG has three separate layers: **MEASURED** (sensor), **INFERRED** (model), and **FALLBACK** (reference only). They must not be summed together. The dashboard does not show large speculative figures when data is missing. Operational audit data is separate and never records passwords, tokens, prompts, or LLM answers.

## Quick diagnosis

| Symptom | Check | Action |
|---|---|---|
| Host does not appear | local-agent state, `agent.log` | Accept UAC, retry the Host agent, and check room configuration. |
| Telemetry is `n/a` | `NodeAgent.exe --test-sensors` | Run as Administrator and check the sensor driver. |
| Agent receives `401/429` | `agent.log` | Check the room/password; do not start another agent. |
| Chat is disabled | model/readiness | Wait for a matching READY node or choose a smaller model. |
| Machine is slow | Task Manager | Keep only one NodeAgent and one llama-server on the Host. |
| No tunnel link | tunnel state | Enable tunnel as admin, wait for `READY`, and check Internet access. |
| LAN worker cannot join | URL/firewall | Use the Host LAN IP, not `localhost`; open TCP 8000 on the Host. |

## Logs and data

- Host data: `%ProgramData%\ThermalOrchestrator\shared`
- DPAPI agent configuration: `%ProgramData%\ThermalOrchestrator\agent\config.json`
- Agent log: next to `NodeAgent.exe` in the running version directory
- Audit CSV: admin endpoint `/api/audit.csv`

Do not manually edit encrypted configuration or delete SQLite files while the Host is running.
