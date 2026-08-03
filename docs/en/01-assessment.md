# Current design assessment

The initial PoC already established sensor ingestion, a basic forecast, and a
pull-based load balancer. The main risks were stale telemetry being presented
as live, a Host that did not join as a real node, optimistic LLM readiness,
duplicate local agents/runtimes, and tunnel state that could be reported ready
before public reachability was verified.

The current implementation addresses these with a local NodeAgent lifecycle,
exact LLM readiness, stale-attempt protection, shared rejoin backoff, tunnel
HTTPS probing, operational audit, and one-EXE update behavior. Remaining
acceptance work requires a second real Windows worker, Named Tunnel credentials,
and a long-running soak test.
