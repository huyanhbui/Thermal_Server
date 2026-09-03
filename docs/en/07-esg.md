# Three-layer ESG accounting

ESG reporting separates three evidence layers: **MEASURED** energy from a
sensor, **DERIVED** energy from a declared physical model, and **PROJECTED**
scale-out figures. They are never summed into one claim. CSV output retains
source, layer, and confidence metadata.

Vietnamese docs use ĐO THẬT / SUY RA / NGOẠI SUY for the same three layers.
Do not label layer 3 as “FALLBACK” — that word is reserved for the linear
thermal-forecast path when `model.pkl` is missing.

The system does not change ESG formulae merely to make a dashboard figure look
better. When direct evidence is insufficient, the UI says so and keeps
derived/projected values visibly separate from measured outcomes.
