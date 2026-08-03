# Scheduler specification

The scheduler evaluates fresh telemetry, forecast thermal headroom, occupancy,
capacity, and policy penalties. It reserves a job before a worker claims it,
preventing concurrent workers from receiving the same work. Expired leases and
node loss are handled as visible lifecycle events.

For ordinary compute jobs, a single eligible node keeps receiving sequential
work rather than leaving the queue stalled. With several eligible nodes, work
is distributed before a node is reused. LLM jobs add exact model readiness and
retry at most once on the next suitable node when the first inference fails.
