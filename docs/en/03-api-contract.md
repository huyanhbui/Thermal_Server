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

## UI routes

Browser aliases (same SPA): `GET /landing`, `/login`, `/app`. Invite deep link
`GET /join?code=` still lands on the join flow. History uses `pushState` where
applicable.

## Chat

`POST /chat` accepts `prompt` (required, ≤32 768 chars), `max_tokens` **1–4096**,
`temperature` 0.0–2.0, and optional `stream`. The dashboard sends
`max_tokens: 4096` (API ceiling). Response is `202` with `job_id` /
`queue_position` — not a synchronous completion.

Default chat queue capacity: **32** pending jobs. Rate limit: **60/min/token**
(`CHAT_MAX`). See [06-security-privacy.md](06-security-privacy.md).

## `GET /api/state`

Admin state includes nodes, ESG three layers (`tier1_measured` /
`tier2_derived` / `tier3_projected`), weather, and:

- `forecast_source`: `"ml"` when `model.pkl` is loaded, else `"linear_fallback"`

Do not invent aspirational fields such as `model_status.per_node_models` in
examples unless the runtime actually emits them. Worker tokens receive a
reduced node list plus `llm_model_id`, not full ESG.
