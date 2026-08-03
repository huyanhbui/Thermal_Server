"""Smoke test cho FakeNode — docs/11 §4."""
from fake_cluster import FakeNode, heterogeneous_cluster


def test_tick_heats_under_load_and_cools_when_idle():
    n = FakeNode("A", idle_temp=40.0, max_temp=90.0,
                 heat_rate=0.5, cool_rate=0.5, cores=4)
    n.tick(1.0, under_load=True)
    assert n.temp > 40.0
    hot = n.temp
    n.tick(1.0, under_load=False)
    assert n.temp < hot


def test_heterogeneous_cluster_has_ten_nodes_and_node10_no_temp():
    cluster = heterogeneous_cluster()
    assert len(cluster) == 10
    assert set(cluster) == {f"Node-{i:02d}" for i in range(1, 11)}
    assert cluster["Node-10"].telemetry(0.0)["cpu_temp"] is None
    assert cluster["Node-07"].heat_rate > cluster["Node-01"].heat_rate
    t = cluster["Node-01"].telemetry(1.0)
    assert t["power_source"] == "sensor" and t["power_w"] is not None
    t7 = cluster["Node-07"].telemetry(1.0)
    assert t7["power_source"] == "none"
