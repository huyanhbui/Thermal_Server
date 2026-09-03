import os
import sqlite3
from pathlib import Path

shared = Path(os.environ["ProgramData"]) / "ThermalOrchestrator" / "shared"
db = shared / "telemetry.db"
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
print("tables:", [r[0] for r in con.execute(
    "SELECT name FROM sqlite_master WHERE type='table'")])
for t in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
    name = t[0]
    n = con.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0]
    print(f"  {name}: {n}")
    cols = [c[1] for c in con.execute(f"PRAGMA table_info([{name}])")]
    if any(x in cols for x in ("energy_j", "energy_source", "tokens_out")):
        print("  cols", cols)
        try:
            print(list(con.execute(
                f"SELECT energy_source, COUNT(*), SUM(energy_j) "
                f"FROM [{name}] GROUP BY energy_source")))
        except Exception as e:
            print("  query err", e)

# also search for esg db nearby
root = Path(os.environ["ProgramData"]) / "ThermalOrchestrator"
for p in root.rglob("*.db"):
    print("db:", p, p.stat().st_size)
