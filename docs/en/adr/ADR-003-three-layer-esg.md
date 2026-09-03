# ADR-003: Three-layer ESG

**Status:** Accepted  
**Date:** 2026-07-31  
**Related:** Vietnamese [ADR-003](../../adr/ADR-003-esg-ba-tang.md), [07-esg.md](../07-esg.md)

Measured sensor data (**MEASURED** / ĐO THẬT), derived model data
(**DERIVED** / SUY RA), and scale projections (**PROJECTED** / NGOẠI SUY)
stay separate so reporting does not overstate evidence. They are three JSON
objects in `/api/state` and three UI blocks — never one summed headline.

Do not call layer 3 “FALLBACK” or “INFERRED”; those names collide with
forecast fallback and older drafts.
