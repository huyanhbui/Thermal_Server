# Operations and incident response

Operate one Host on port 8000 and observe local-agent, node freshness, model readiness, queue, and tunnel state. The primary evidence is the Host log, agent log, SQLite audit, and dashboard state; do not rely on stale card values as live telemetry.

For incidents, distinguish room authentication, network reachability, sensor access, stale telemetry, model mismatch, queue capacity, and tunnel readiness. Restart only owned Host/NodeAgent/llama child processes, preserve data before migration, and do not erase configuration or audit evidence.
