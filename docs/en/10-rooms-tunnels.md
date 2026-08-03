# Rooms and tunnels

A room separates worker/admin credentials, node membership, audit, and session lifecycle. The worker setup link contains only a room code; the worker still enters its password locally. A local Host agent uses the same model and sensor path as a remote worker.

Quick Tunnel is for temporary testing and uses an application-owned empty profile so a personal cloudflared configuration cannot break it. Named Tunnel uses a write-only token and stable hostname. Neither mode returns an invite until the public HTTPS probe succeeds.
