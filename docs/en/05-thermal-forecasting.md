# Thermal forecasting

The Host builds a recent sensor window for every node and predicts the maximum
CPU temperature over the next three minutes. A trained Random Forest is used
when available; a constrained linear trend remains a fallback for an untrained
installation.

`/api/state` exposes `forecast_source`: `"ml"` when `model.pkl` is loaded,
otherwise `"linear_fallback"`. Dashboard badges (English UI):

- **Forecast: ML model**
- **Forecast: Linear fallback (not ML)**

Never present the linear fallback as a trained ML model.

## Model path and training

When `THERMAL_DATA_DIR` is set (packaged Host default:
`%ProgramData%\ThermalOrchestrator\shared`), both Forecaster and
`train_model.py` read/write `model.pkl` in that data directory next to
`telemetry.db` — not relative to the Host process CWD.

```
# Dev (CWD = server/)
python train_model.py

# Packaged Host
set THERMAL_DATA_DIR=%ProgramData%\ThermalOrchestrator\shared
python train_model.py
# → writes shared\model.pkl; restart Host → forecast_source=ml
```

Forecast functions accept a supplied time so behavior can be tested without a
real clock. A node needs enough fresh samples to build features; otherwise the
Host must show insufficient data instead of presenting an invented forecast.
The same forecast value used for a dispatch decision is exposed to the
dashboard and audit trail.
