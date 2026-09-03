import os
import sys
from pathlib import Path

sys.path.insert(0, r"F:\FileLapTrinhF\Thermal_Server\server")
shared = Path(os.environ["ProgramData"]) / "ThermalOrchestrator" / "shared"
os.environ["THERMAL_DATA_DIR"] = str(shared)
from store import TelemetryStore
from esg import compute_report

store = TelemetryStore(str(shared / "telemetry.db"))
events = store.esg_events()
print("events", len(events))
from collections import Counter
print(Counter(e["event_type"] for e in events))
# peek job details
for e in events[:5]:
    print(e["event_type"], e.get("detail"))
r = compute_report(events)
t1 = r["tier1_measured"]
print("t1", {k: t1.get(k) for k in (
    "samples", "confidence", "j_per_token", "improvement_pct",
    "sensor_nodes")})
print("t2 keys sample", {k: r["tier2_derived"].get(k) for k in (
    "kwh_leakage_saved", "kwh_fan_saved", "kwh_cooling_saved")})
