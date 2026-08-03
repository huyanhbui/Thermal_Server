# Testing strategy

Required checks include focused regression tests before each behavior change, the complete Python suite, .NET tests/build, and review of the staged diff. Browser acceptance covers landing/auth/dashboard, password visibility, copy fallback, responsive layouts, accessibility, and WebSocket streaming.

Production-like acceptance also checks Host UAC startup, real telemetry, model readiness after a switch, retry behavior, child-runtime cleanup, restart, worker setup, tunnel reachability, audit filtering, and long-running soak.
