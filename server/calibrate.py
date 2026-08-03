"""Calibration mode: cycles CPU load up and down on each node while the
server records telemetry, producing training data for train_model.py.
Total ~20 min for 2 nodes. Forecast/generator loops are OFF in this mode."""
import asyncio
import logging

log = logging.getLogger("calibrate")

# per node: (phase name, seconds, job cores [0=all], enqueue interval seconds)
PHASES = [("idle", 120, None, None),
          ("light", 180, 2, 12),
          ("heavy", 240, 0, 8),
          ("cooldown", 120, None, None)]

async def calibration_task(state):
    await asyncio.sleep(10)   # let agents connect
    nodes = []
    while not nodes:          # wait until at least one agent has reported
        nodes = state.store.nodes()
        if not nodes:
            log.info("[CALIBRATE] waiting for agents to report in...")
            await asyncio.sleep(5)
    log.info("[CALIBRATE] starting load cycles for nodes: %s", nodes)
    for node in sorted(nodes):
        for name, seconds, cores, interval in PHASES:
            log.info("[CALIBRATE] %s: phase '%s' for %ss", node, name, seconds)
            if interval is None:
                await asyncio.sleep(seconds)
                continue
            elapsed = 0
            while elapsed < seconds:
                state.balancer.enqueue_job(duration_s=interval, cores=cores,
                                           target=node)
                await asyncio.sleep(interval)
                elapsed += interval
    log.info("[CALIBRATE] finished. Now run: python train_model.py "
             "then restart: python server.py")
