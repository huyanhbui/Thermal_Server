# API contract

The API follows a pull-based worker model. `/join` issues an in-memory token
after room/password verification; `/ingest`, `/nodes/ready`, `/jobs/next`, job
events, and job results authenticate the node from that token.

Key Host APIs include room bootstrap/recovery, local-agent start, credential
rotation, state, audit CSV, and tunnel configuration/enablement. Job results
and streaming events carry `attempt_id`; stale attempts are rejected and final
results are idempotent by job ID plus attempt ID.

Browser WebSocket events include node state, local-agent state, model state,
tunnel state, `chat_token`, and `chat_result`. The periodic state endpoint is
the recovery path if a WebSocket reconnects.
