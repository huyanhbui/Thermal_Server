"""P1: hai lifecycle writer phải serialize; chỉ owner reset gate."""
from __future__ import annotations

import threading
import time

from lifecycle import LifecycleGate


def test_second_writer_waits_until_first_finish_releases():
    """Writer A giữ finish_fn: B chưa purge/finish; mutation không vào; nhả A → B chạy."""
    gate = LifecycleGate()
    order = []
    a_in_finish = threading.Event()
    release_a = threading.Event()
    b_started_purge = threading.Event()
    mutation_entered = threading.Event()
    a_done = threading.Event()
    b_done = threading.Event()

    def writer_a():
        def purge():
            order.append("A-purge")

        def finish():
            order.append("A-finish-enter")
            a_in_finish.set()
            assert release_a.wait(timeout=5)
            order.append("A-finish-exit")

        gate.run(
            purge_fn=purge,
            finish_fn=finish,
            set_accepting=lambda a: order.append(f"A-accepting={a}"),
        )
        a_done.set()

    def writer_b():
        assert a_in_finish.wait(timeout=5)

        def purge():
            order.append("B-purge")
            b_started_purge.set()

        def finish():
            order.append("B-finish")

        gate.run(
            purge_fn=purge,
            finish_fn=finish,
            set_accepting=lambda a: order.append(f"B-accepting={a}"),
        )
        b_done.set()

    def try_mutation():
        assert a_in_finish.wait(timeout=5)
        # Trong lúc A còn finish: mutation_section không được vào
        entered = False
        try:
            with gate.mutation_section(timeout=0.3):
                entered = True
                mutation_entered.set()
        except Exception:
            entered = False
        order.append(f"mutation-during-A={entered}")
        assert entered is False
        assert not b_started_purge.is_set()
        release_a.set()

    ta = threading.Thread(target=writer_a)
    tb = threading.Thread(target=writer_b)
    tm = threading.Thread(target=try_mutation)
    ta.start()
    tb.start()
    tm.start()
    tm.join(timeout=8)
    ta.join(timeout=8)
    b_done.wait(timeout=8)
    tb.join(timeout=8)

    assert a_done.is_set()
    assert b_done.is_set()
    assert "A-purge" in order
    assert "A-finish-enter" in order
    # B không purge trước khi A xong finish
    assert order.index("B-purge") > order.index("A-finish-exit")
    assert "B-finish" in order
    assert "mutation-during-A=False" in order
