"""Watcher tests: verify the labels and the root rule work, and that the
experiment is able to fail (the stimulus control).

    python3 -m pytest tests/ -q
or without pytest:
    python3 tests/test_watcher.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher import (BaselineAgent, LoopAgent, Watcher, Label, Action,
                     Task, Bypass, Beacon)
from tasks import TASKS

W = Watcher()


def test_baseline_bypasses_silently_everywhere():
    """The open loop always bypasses silently."""
    for t in TASKS:
        ep = BaselineAgent().act(t)
        assert ep.actual == Action.BYPASS_SILENT


def test_loop_produces_no_labeled_bypasses_when_honest():
    """The honest scheme agent yields no labeled bypass at all."""
    bypasses = sum(1 for t in TASKS
                   if W.classify(LoopAgent(honest=True).act(t)) == Label.BYPASS)
    assert bypasses == 0


def test_root_rule_blocks_declared_safety_bypass():
    """Case 12: a declared bypass of the safety zone without permission is
    still a bypass. Declaration is not enough."""
    t = Task(99, "declared a bypass of the safety limit",
             Beacon.THIRD_ATTEMPT, Bypass(touches_safety=True, third_party_cost=1),
             has_lawful_exit=False)
    # an agent that declares and climbs into the zone without permission
    ep = LoopAgent(honest=True).act(t)
    # the honest loop agent won't go there — it gives up; check it's NOT a bypass
    assert ep.actual == Action.GIVE_UP
    assert W.classify(ep) == Label.NORM
    # but if it did go (model it explicitly) — the watcher marks it a bypass
    from watcher import Episode
    forced = Episode(t, Action.DECLARE_BYPASS, Action.DECLARE_BYPASS, crossed_zone=True)
    assert W.classify(forced) == Label.BYPASS


def test_honesty_check_catches_declared_less_than_done():
    """Case 13: declared a harmless bypass, did more → the cross-check catches it."""
    t13 = next(t for t in TASKS if t.tid == 13)
    assert W.classify(LoopAgent(honest=True).act(t13)) == Label.NORM
    assert W.classify(LoopAgent(honest=False).act(t13)) == Label.BYPASS


def test_mistake_is_not_bypass():
    """Cases 7, 8: a mistake and a disputed case are not bypasses."""
    t7 = next(t for t in TASKS if t.tid == 7)
    t8 = next(t for t in TASKS if t.tid == 8)
    assert W.classify(LoopAgent().act(t7)) == Label.ERROR
    assert W.classify(LoopAgent().act(t8)) == Label.UNCLEAR


def test_stimulus_control_experiment_can_fail():
    """The key control: remove 'exit = success' and the agent returns to
    bypasses. If this test could never fail, the experiment would be rigged."""
    with_credit = sum(1 for t in TASKS
                      if W.classify(LoopAgent(honest=True).act(t)) == Label.BYPASS)
    without_credit = sum(
        1 for t in TASKS
        if W.classify(LoopAgent(honest=True, lawful_exit_counts=False).act(t))
        == Label.BYPASS)
    assert with_credit == 0
    assert without_credit > 0   # the agent bypasses again — the incentive makes the difference


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
