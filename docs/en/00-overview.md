# Technical overview

Thermal Orchestrator is a Windows proof of concept for safely dispatching
compute work according to real thermal and power telemetry. The Host owns
rooms, authentication, SQLite persistence, forecasting, scheduling, ESG, and
the browser API. NodeAgent runs on the Host and workers, reads sensors, polls
for work, and can run llama.cpp locally.

Workers are outbound-only. The Host does not expose a listener on workers or
infer node identity from request fields. A node becomes schedulable only after
fresh telemetry and, for LLM jobs, an exact readiness report.

The system has two workloads: ordinary compute jobs such as thermal burn or
calibration tasks, and LLM chat jobs. Ordinary jobs use temperature/headroom
and capacity; LLM jobs additionally require the chosen model, hash, generation,
and runtime identity.
