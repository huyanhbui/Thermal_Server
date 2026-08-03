# Thermal forecasting

The Host builds a recent sensor window for every node and predicts the maximum
CPU temperature over the next three minutes. A trained Random Forest is used
when available; a constrained linear trend remains a fallback for an untrained
installation.

Forecast functions accept a supplied time so behavior can be tested without a
real clock. A node needs enough fresh samples to build features; otherwise the
Host must show insufficient data instead of presenting an invented forecast.
The same forecast value used for a dispatch decision is exposed to the
dashboard and audit trail.
