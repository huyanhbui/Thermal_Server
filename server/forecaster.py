"""Predicts each node's max CPU temperature over the next 3 minutes.

Model output is ΔT (rise over the horizon). Callers use:
    predicted_max = current_temp + ΔT_pred

Uses model.pkl (Random Forest, trained by train_model.py) when present,
otherwise a conservative linear-trend fallback so the loop works
pre-calibration.
"""
import logging
import os

import joblib
import numpy as np

from features import build_features

log = logging.getLogger("forecaster")
HORIZON_MIN = 3.0
FALLBACK_CAP_C = 20.0


class Forecaster:
    def __init__(self, model_path="model.pkl"):
        self.model = None
        if os.path.exists(model_path):
            self.model = joblib.load(model_path)
            log.info("[FORECAST] Loaded trained model from %s", model_path)
        else:
            log.warning(
                "[FORECAST] No model at %s - using linear-trend fallback. "
                "Run calibration + train_model.py for real forecasts.",
                model_path)

    @property
    def model_loaded(self):
        return self.model is not None

    def predict_delta_t(self, samples, idle_baseline: float = 40.0):
        """Return predicted temperature rise (°C) over HORIZON_MIN minutes."""
        feats = build_features(samples, idle_baseline=idle_baseline)
        if feats is None:
            return None
        if self.model is not None:
            return float(self.model.predict(np.array([feats]))[0])
        slope = feats[2]
        return min(max(slope, 0.0) * HORIZON_MIN, FALLBACK_CAP_C)

    def predict_max_temp(self, samples, idle_baseline: float = 40.0):
        """Return predicted max absolute °C = current + ΔT."""
        feats = build_features(samples, idle_baseline=idle_baseline)
        if feats is None:
            return None
        current = feats[0]
        if self.model is not None:
            delta = float(self.model.predict(np.array([feats]))[0])
        else:
            slope = feats[2]
            delta = min(max(slope, 0.0) * HORIZON_MIN, FALLBACK_CAP_C)
        return current + delta
