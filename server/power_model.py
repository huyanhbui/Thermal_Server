"""Đường dự phòng công suất từ power_model.json (docs/08 §5, §8).

P = a + b·util + c·temp. Kết quả luôn gắn nhãn source='model' —
chỉ vào ESG Tầng 2, không bao giờ trộn vào J/token Tầng 1.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

log = logging.getLogger("server")


@dataclass
class PowerModel:
    a: float
    b: float
    c: float
    temp_term_used: bool
    p_idle_w: float | None
    p_max_w: float | None
    leakage_w_per_c: float | None
    path: str

    def estimate_w(self, cpu_util: float | None,
                   cpu_temp: float | None) -> float | None:
        """Ước lượng W. Thiếu util → None (không bịa)."""
        if cpu_util is None:
            return None
        try:
            util = float(cpu_util)
            p = self.a + self.b * util
            if self.temp_term_used and cpu_temp is not None:
                p += self.c * float(cpu_temp)
            return max(0.0, p)
        except (TypeError, ValueError):
            return None


def load_power_model(path: str) -> PowerModel | None:
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log.warning("[ESG] không đọc được power_model %s: %s", path, e)
        return None
    coef = raw.get("coefficients") or {}
    try:
        a = float(coef["a"])
        b = float(coef["b"])
        c = float(coef.get("c") or 0.0)
    except (KeyError, TypeError, ValueError):
        log.warning("[ESG] power_model thiếu hệ số a/b: %s", path)
        return None
    leakage = raw.get("leakage_w_per_c")
    if leakage is not None:
        try:
            leakage = float(leakage)
        except (TypeError, ValueError):
            leakage = None
    pm = PowerModel(
        a=a, b=b, c=c,
        temp_term_used=bool(raw.get("temp_term_used", c != 0.0)),
        p_idle_w=_opt_float(raw.get("p_idle_w")),
        p_max_w=_opt_float(raw.get("p_max_w")),
        leakage_w_per_c=leakage,
        path=path,
    )
    log.info("[ESG] đã nạp power_model từ %s (leakage=%s)",
             path, pm.leakage_w_per_c)
    return pm


def _opt_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def apply_leakage_to_esg_config(esg_config: dict,
                                pm: PowerModel | None) -> None:
    """Nếu ESG chưa có leakage đo được, lấy từ power_model."""
    if pm is None or pm.leakage_w_per_c is None:
        return
    if esg_config.get("leakage_w_per_c") is None:
        esg_config["leakage_w_per_c"] = pm.leakage_w_per_c
