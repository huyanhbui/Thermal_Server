# ADR-001: Reservation instead of push

Workers pull jobs outbound. The Host reserves a job for a node before it is claimed, preventing duplicate delivery and allowing leases to expire safely.
