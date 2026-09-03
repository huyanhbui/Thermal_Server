# Security and privacy

Workers are outbound-only and their identity is derived from a bearer token,
not a node name supplied by a request. Room credentials use salted verifiers;
the local agent password is protected with machine-scoped Windows DPAPI and
restricted ACLs. Plaintext legacy configuration is migrated once.

Session tokens are memory-only. Audit records include operational outcome,
role, node, request ID, source class, and filtered error detail, but never a
password, token, full IP address, prompt, or LLM answer. Password policies are
enforced by the backend, including the 12-character tunnel requirement.

## Rate limits (`server/rate_limit.py`)

| Endpoint | Limit | On exceed |
|---|---|---|
| `POST /join` | 5/min/IP | 429 + exponential backoff |
| `POST /ingest` | 2/s/token (`INGEST_MAX`) | 429 |
| `POST /chat` | 60/min/token (`CHAT_MAX`) | 429 |
| Job pull (`/jobs/next`, …) | 30/min/token (`JOBS_MAX`) | 429 |
| `POST /jobs/.../events` | 600/min/token (`JOB_EVENTS_MAX`) | 429 |
| Other authenticated routes | 60/min/token (`DEFAULT_MAX`) | 429 |

`JOB_EVENTS` is separate from the default 60/min bucket so a long streamed
chat reply cannot exhaust admin/worker quota.
