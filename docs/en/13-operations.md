# Operations and incident response

Operate one Host on port 8000 and observe local-agent, node freshness, model
readiness, queue, and tunnel state. The primary evidence is the Host log, agent
log, SQLite audit, and dashboard state; do not rely on stale card values as
live telemetry.

## Forecast / ML badge

| Symptom | Check | Fix |
|---|---|---|
| Badge **Forecast: Linear fallback (not ML)** | `model.pkl` under `THERMAL_DATA_DIR` (`%ProgramData%\ThermalOrchestrator\shared`) | `python train_model.py` with that env set (needs enough telemetry windows), then **restart Host**; expect `[FORECAST] Loaded trained model` and `forecast_source=ml` |

Chat queue full means **32** pending jobs (`max_queue`). ESG UI labels are
**MEASURED / DERIVED / PROJECTED** — not INFERRED/FALLBACK.

For incidents, distinguish room authentication, network reachability, sensor
access, stale telemetry, model mismatch, queue capacity, and tunnel readiness.
Restart only owned Host/NodeAgent/llama child processes, preserve data before
migration, and do not erase configuration or audit evidence.
