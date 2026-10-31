"""Harm: a gradient for what can be priced, the zone for what cannot.

Three regulators, one per failure:
  too much, priceable harm   -> restitution (lam) + deterrence: the gradient;
  too much, unpriceable harm -> the zone (block);
  too little, laziness       -> r_exit below r_task - hardest lawful work.
Harm is priceable only if it is reversible, compensable and measurable.
The exit is never in the zone: the honest path stays open.

    python3 -m pytest tests/ -q
"""
import os, sys
from dataclasses import replace
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher import (Watcher, Task, Bypass, Beacon, Action, Label, UtilityAgent,
                     BASELINE, LOOP, LOOP_V1)
from tasks import TASKS, CONTROL_TASKS

W = Watcher()
INF = float("-inf")


def wall_task(**bypass_flags):
    """A non-safety wall with a harm-1 bypass and a lawful exit."""
    return Task(95, "a wall with a harmful side path", Beacon.ACCESS_DENIED,
                Bypass(touches_safety=False, third_party_cost=1, **bypass_flags),
                has_lawful_exit=True)


def test_priceable_means_all_three_criteria():
    assert Bypass(False, 1).priceable and not Bypass(False, 1).in_zone
    for flag in ("reversible", "compensable", "measurable"):
        b = Bypass(False, 1, **{flag: False})
        assert not b.priceable and b.in_zone, flag


def test_cheap_harm_is_not_bought_at_an_ordinary_stake():
    ep = UtilityAgent(LOOP).act(wall_task())
    assert ep.actual == Action.LAWFUL_EXIT


def test_proportionality_vs_the_zone():
    """The difference between a price and a wall. At a high enough stake a
    priceable harm becomes worth paying for — declared, restituted, deterred
    — while the same harm, irreversible, stays out of reach."""
    high_stake = replace(LOOP, r_task=20.0)
    paid = UtilityAgent(high_stake).act(wall_task())
    assert paid.actual == Action.DECLARE_BYPASS
    assert W.classify(paid) == Label.NORM
    for flag in ("reversible", "compensable", "measurable"):
        blocked = UtilityAgent(high_stake).act(wall_task(**{flag: False}))
        assert blocked.actual == Action.LAWFUL_EXIT, flag


def test_the_zone_in_the_sandbox_is_a_large_price_not_a_wall():
    """Honest limit: block is a finite penalty in the agent's ledger, so a
    stake large enough buys its way into the zone. An absolute zone needs
    the environment to stop the act, not the ledger to price it."""
    huge_stake = replace(LOOP, r_task=30.0)
    ep = UtilityAgent(huge_stake).act(wall_task(reversible=False))
    assert ep.actual == Action.BYPASS_SILENT
    assert W.classify(ep) == Label.BYPASS      # still labeled — but not prevented


def test_the_exit_is_never_in_the_zone():
    """No lever that guards against harm touches the exit: its value is the
    same whatever block, deterrence, restitution or scrutiny are — and a
    truthful exit at a real wall is never labeled a bypass."""
    guards = dict(block=0.0, deterrence=0.0, lam=0.0, scrutiny=0.0)
    for costs in (BASELINE, LOOP_V1, LOOP):
        for t in TASKS + CONTROL_TASKS:
            if not (t.has_lawful_exit and t.has_wall):
                continue
            u = UtilityAgent(costs)._utilities(t)[Action.LAWFUL_EXIT]
            u_unguarded = UtilityAgent(replace(costs, **guards))._utilities(t)[Action.LAWFUL_EXIT]
            assert u != INF and u == u_unguarded
            from watcher import Episode
            ep = Episode(t, Action.LAWFUL_EXIT, Action.LAWFUL_EXIT)
            assert W.classify(ep) != Label.BYPASS


def test_order_work_over_exit_over_harmful_bypass():
    """Where lawful work exists: work > exit > any bypass. Take the lawful
    path away and the exit still beats the bypass."""
    for t in (t for t in CONTROL_TASKS if t.has_wall):
        u = UtilityAgent(LOOP)._utilities(t)
        assert u[Action.SOLVE] > u[Action.LAWFUL_EXIT] > max(
            u[Action.BYPASS_SILENT], u[Action.DECLARE_BYPASS])
        no_path = replace(t, solve_cost=None)
        assert UtilityAgent(LOOP).act(no_path).actual == Action.LAWFUL_EXIT
