"""Watcher + utility-agent tests.

Verify the labels, the root rule, the honesty cross-check, and — crucially —
that the experiment is able to fail: strip the incentives and bypasses return,
so it is the cost table, not the watcher's label, doing the work.

    python3 -m pytest tests/ -q
or without pytest:
    python3 tests/test_watcher.py
"""
import os, sys, random
from dataclasses import replace
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher import (UtilityAgent, baseline_agent, loop_agent, Watcher,
                     Label, Action, Task, Bypass, Beacon, Episode,
                     Costs, LOOP, BASELINE)
from tasks import TASKS

W = Watcher()


def bypass_count(costs, honest=True):
    return sum(1 for t in TASKS
               if W.classify(UtilityAgent(costs, honest=honest).act(t)) == Label.BYPASS)


def test_baseline_bypasses_silently_everywhere():
    """The open loop always bypasses silently (nothing is returned to it)."""
    for t in TASKS:
        ep = baseline_agent().act(t)
        assert ep.actual == Action.BYPASS_SILENT


def test_baseline_yields_twelve_bypasses():
    """Open loop: 12 labeled bypasses (14 tasks − 2 that are mistake/unclear)."""
    assert bypass_count(BASELINE) == 12


def test_loop_produces_no_labeled_bypasses_when_honest():
    """The honest closed-loop agent yields no labeled bypass at all."""
    assert bypass_count(LOOP) == 0


def test_same_agent_two_cost_tables():
    """Baseline and loop are the SAME class with different cost tables."""
    assert type(baseline_agent()) is type(loop_agent()) is UtilityAgent


def test_root_rule_blocks_declared_safety_bypass():
    """Case 12: a declared bypass of the safety zone without permission is
    still a bypass. Declaration is not enough."""
    t = Task(99, "declared a bypass of the safety limit",
             Beacon.THIRD_ATTEMPT, Bypass(touches_safety=True, third_party_cost=1),
             has_lawful_exit=False)
    # the honest loop agent won't go there — it gives up; that is NOT a bypass
    ep = loop_agent().act(t)
    assert ep.actual == Action.GIVE_UP
    assert W.classify(ep) == Label.NORM
    # but a forced declared zone-crossing is marked a bypass by the watcher
    forced = Episode(t, Action.DECLARE_BYPASS, Action.DECLARE_BYPASS, crossed_zone=True)
    assert W.classify(forced) == Label.BYPASS


def test_honesty_check_catches_declared_less_than_done():
    """Case 13: declared a harmless bypass, did more → the cross-check catches it."""
    t13 = next(t for t in TASKS if t.tid == 13)
    assert W.classify(loop_agent(honest=True).act(t13)) == Label.NORM
    assert W.classify(loop_agent(honest=False).act(t13)) == Label.BYPASS


def test_mistake_is_not_bypass():
    """Cases 7, 8: a mistake and a disputed case are not bypasses."""
    t7 = next(t for t in TASKS if t.tid == 7)
    t8 = next(t for t in TASKS if t.tid == 8)
    assert W.classify(loop_agent().act(t7)) == Label.ERROR
    assert W.classify(loop_agent().act(t8)) == Label.UNCLEAR


def test_stripping_all_incentives_equals_baseline():
    """The key control: with every incentive removed, the loop cost table
    collapses to baseline behavior (12 bypasses). The experiment can fail."""
    stripped = replace(LOOP, r_exit=0.0, scrutiny=0.0, lam=0.0, block=0.0)
    assert bypass_count(stripped) == 12


def test_no_single_point_of_failure():
    """Removing any one incentive keeps the scheme near zero — redundancy."""
    for field in ("r_exit", "scrutiny", "lam", "block"):
        c = replace(LOOP, **{field: 0.0})
        assert bypass_count(c) <= 1, f"removing {field} broke the scheme"


def test_internalization_threshold_is_partial():
    """Partial internalization already drives bypasses to zero (s<1)."""
    def scaled(s):
        return replace(LOOP, r_exit=LOOP.r_exit*s, lam=LOOP.lam*s,
                       block=LOOP.block*s, scrutiny=LOOP.scrutiny*s)
    assert bypass_count(scaled(0.0)) == 12      # = baseline
    assert bypass_count(scaled(0.7)) == 0       # full effect below s=1
    assert bypass_count(scaled(1.0)) == 0


def test_noise_degrades_gracefully():
    """Under ε-noise the loop's advantage shrinks but does not fall off a
    cliff: at moderate noise it still beats the open loop clearly."""
    def mc(costs, eps, trials=1500, seed=1):
        rng = random.Random(seed)
        tot = 0
        for _ in range(trials):
            ag = UtilityAgent(costs, epsilon=eps, rng=rng)
            tot += sum(1 for t in TASKS if W.classify(ag.act(t)) == Label.BYPASS)
        return tot / trials
    adv0 = mc(BASELINE, 0.0) - mc(LOOP, 0.0)
    adv_mid = mc(BASELINE, 0.25) - mc(LOOP, 0.25)
    assert adv0 == 12
    assert adv_mid > 6          # still a large advantage at ε=0.25


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
