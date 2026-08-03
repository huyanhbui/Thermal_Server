# Security and privacy

Workers are outbound-only and their identity is derived from a bearer token,
not a node name supplied by a request. Room credentials use salted verifiers;
the local agent password is protected with machine-scoped Windows DPAPI and
restricted ACLs. Plaintext legacy configuration is migrated once.

Session tokens are memory-only. Audit records include operational outcome,
role, node, request ID, source class, and filtered error detail, but never a
password, token, full IP address, prompt, or LLM answer. Password policies are
enforced by the backend, including the 12-character tunnel requirement.
