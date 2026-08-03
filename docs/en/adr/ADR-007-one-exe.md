# ADR-007: One Windows EXE

A self-contained .NET bootstrapper packages the Host runtime and NodeAgent, installs versioned payloads under ProgramData, requests UAC, and updates only owned processes.
