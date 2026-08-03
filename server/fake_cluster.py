"""Bộ giả lập 10 node dị chủng — docs/11 §4.

Thời gian là tham số. Không time.sleep() ở đâu cả. Dùng lại ở G4–G7.
"""
from __future__ import annotations


class FakeNode:
    """Worker mô phỏng với mô hình nhiệt bậc một.

    under_load → tiến về max_temp với heat_rate;
    rảnh → tiến về idle_temp với cool_rate.
    """

    def __init__(self, name, idle_temp, max_temp, heat_rate, cool_rate,
                 cores, has_power_sensor=True, tokens_per_s=40.0,
                 *, reports_temp=True, p_idle_w=15.0, p_max_w=65.0):
        self.name = name
        self.idle_temp = idle_temp
        self.max_temp = max_temp
        self.heat_rate = heat_rate
        self.cool_rate = cool_rate
        self.cores = cores
        self.has_power_sensor = has_power_sensor
        self.tokens_per_s = tokens_per_s
        self.reports_temp = reports_temp
        self.p_idle_w = p_idle_w
        self.p_max_w = p_max_w
        self.temp = idle_temp if reports_temp and idle_temp is not None else None
        self.under_load = False
        self.cpu_util = 5.0

    def tick(self, dt, under_load):
        """Cập nhật nhiệt. dt do test truyền — không dùng đồng hồ thật."""
        self.under_load = under_load
        if not self.reports_temp or self.temp is None:
            self.cpu_util = 90.0 if under_load else 5.0
            return
        target = self.max_temp if under_load else self.idle_temp
        rate = self.heat_rate if under_load else self.cool_rate
        self.temp += (target - self.temp) * rate * dt
        self.cpu_util = 90.0 if under_load else 5.0

    def telemetry(self, now):
        power_w = None
        power_source = "none"
        if self.has_power_sensor and self.reports_temp:
            frac = 0.9 if self.under_load else 0.1
            if (self.temp is not None and self.max_temp is not None
                    and self.idle_temp is not None
                    and self.max_temp != self.idle_temp):
                span = self.max_temp - self.idle_temp
                frac = max(0.0, min(1.0,
                    (self.temp - self.idle_temp) / span))
            power_w = self.p_idle_w + frac * (self.p_max_w - self.p_idle_w)
            power_source = "sensor"
        return {
            "ts": now,
            "cpu_temp": self.temp if self.reports_temp else None,
            "cpu_util": self.cpu_util,
            "power_w": power_w,
            "power_source": power_source,
        }


def heterogeneous_cluster():
    """Cụm 10 node cố ý dị chủng theo bảng docs/11 §4.

    heat/cool rate chọn để C5 (Node-07 gắn cờ trước Node-01) và C9 đứng vững.
    """
    nodes = []
    for i in range(1, 4):
        nodes.append(FakeNode(
            f"Node-{i:02d}", idle_temp=32.0, max_temp=68.0,
            heat_rate=0.02, cool_rate=0.05, cores=16,
            has_power_sensor=True, tokens_per_s=70.0,
            p_idle_w=20.0, p_max_w=120.0))
    for i in range(4, 7):
        nodes.append(FakeNode(
            f"Node-{i:02d}", idle_temp=45.0, max_temp=88.0,
            heat_rate=0.05, cool_rate=0.04, cores=8,
            has_power_sensor=True, tokens_per_s=35.0,
            p_idle_w=12.0, p_max_w=55.0))
    for i in range(7, 9):
        nodes.append(FakeNode(
            f"Node-{i:02d}", idle_temp=52.0, max_temp=95.0,
            heat_rate=0.12, cool_rate=0.06, cores=4,
            has_power_sensor=False, tokens_per_s=18.0))
    nodes.append(FakeNode(
        "Node-09", idle_temp=48.0, max_temp=92.0,
        heat_rate=0.10, cool_rate=0.03, cores=8,
        has_power_sensor=True, tokens_per_s=25.0,
        p_idle_w=25.0, p_max_w=90.0))
    nodes.append(FakeNode(
        "Node-10", idle_temp=None, max_temp=None,
        heat_rate=0.0, cool_rate=0.0, cores=8,
        has_power_sensor=False, tokens_per_s=40.0,
        reports_temp=False))
    return {n.name: n for n in nodes}
