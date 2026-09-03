# System architecture

The Host runs FastAPI on port 8000 and stores operational state in SQLite.
Browser administrators use HTTP plus WebSocket; workers use outbound HTTP only.
The Host receives telemetry, produces forecasts, marks unsuitable nodes, and
reserves jobs. Workers long-poll for jobs, execute them, and post events/results.

Room passwords are verified server-side. Tokens are in-memory sessions and are
revoked on restart, close, or credential rotation. The Host local agent uses
the same NodeAgent, SensorReader, and llama.cpp path as a remote worker rather
than a server-side pseudo-node.

Important boundaries are sensor versus model data, **MEASURED / DERIVED /
PROJECTED** ESG layers (never summed), and ordinary compute scheduling versus
LLM model-readiness scheduling. Thermal forecast provenance is separate:
`forecast_source` is `ml` or `linear_fallback` — do not confuse ESG PROJECTED
with forecast fallback.
