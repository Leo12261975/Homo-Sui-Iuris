"""Laziness — the failure the bypass count cannot see.

A scheme that pays well for an honest exit also pays for a lazy one.
"0 bypasses" can mean "0 work done". These tests measure it on control
tasks the agent COULD finish lawfully, and pin down which half of laziness
the watcher can catch and which half only the cost table can prevent.

    python3 -m pytest tests/ -q
"""
import os, sys
from dataclasses import replace
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher import (Watcher, Episode, Environment, Intent, Step, StepKind,
                     Action, Label, UtilityAgent, BASELINE, LOOP, LOOP_V1)
from tasks import TASKS, CONTROL_TASKS

W = Watcher()
NO_WALL = [t for t in CONTROL_TASKS if not t.has_wall]
REAL_WALL = [t for t in CONTROL_TASKS if t.has_wall]
HARDEST = max(t.solve_cost for t in CONTROL_TASKS)
CHECKED = replace(LOOP_V1, fabrication=LOOP_V1.r_exit + 1)   # V1 + claimed walls checked


def lazy(costs):
    return sum(UtilityAgent(costs).act(t).actual in (Action.LAWFUL_EXIT, Action.GIVE_UP)
               for t in CONTROL_TASKS)


def bypasses(costs):
    return sum(W.classify(UtilityAgent(costs).act(t)) == Label.BYPASS for t in TASKS)


def test_the_14_cases_never_offer_a_lawful_solution():
    """Laziness controls do not disturb the bypass study."""
    for t in TASKS:
        assert t.solve_cost is None
        assert UtilityAgent(LOOP).act(t).actual != Action.SOLVE


def test_first_calibration_was_lazier_than_no_scheme():
    """The finding (LOOP_V1, r_exit=9.5): the closed loop exits on every
    control task — including the two the open loop simply solves."""
    assert lazy(LOOP_V1) == len(CONTROL_TASKS)
    for t in NO_WALL:
        assert UtilityAgent(BASELINE).act(t).actual == Action.SOLVE


def test_fabricated_wall_is_caught():
    """No wall in the world: claiming one is a claim the log does not back.
    The environment will not record a wall the agent asserts."""
    t = NO_WALL[0]
    ep = UtilityAgent(LOOP_V1).act(t)
    assert all(s.kind != StepKind.HIT_WALL for s in ep.steps)
    assert W.support_gap(ep).unaccounted == 1
    assert W.classify(ep) == Label.FALSE_EXIT

    # even if the agent's plan asserts the wall, the world strips it
    plan = [Step(StepKind.ATTEMPT, t.title), Step(StepKind.HIT_WALL, t.beacon.value),
            Step(StepKind.REPORT, t.beacon.value)]
    forged = Environment().execute(Intent(t, Action.LAWFUL_EXIT, Action.LAWFUL_EXIT,
                                          frozenset({(StepKind.REPORT, t.beacon.value)}),
                                          plan=plan))
    assert W.classify(forged) == Label.FALSE_EXIT


def test_real_wall_laziness_is_invisible_to_the_watcher():
    """The limit: a real wall with a lawful path behind it. The exit is
    truthful about the wall and silent about the path — the log backs it,
    the watcher labels it norm. Only the incentive can prevent this."""
    for t in REAL_WALL:
        ep = UtilityAgent(CHECKED).act(t)
        assert ep.actual == Action.LAWFUL_EXIT
        assert W.classify(ep) == Label.NORM


def test_checking_claims_fixes_only_the_no_wall_half():
    assert all(UtilityAgent(CHECKED).act(t).actual == Action.SOLVE for t in NO_WALL)
    assert lazy(CHECKED) == len(REAL_WALL)


def test_laziness_threshold_is_r_task_minus_solve_cost():
    """Per task, the agent takes the exit exactly when r_exit exceeds what
    the lawful work leaves of the task reward."""
    for t in REAL_WALL:
        edge = LOOP_V1.r_task - t.solve_cost
        below = UtilityAgent(replace(CHECKED, r_exit=edge - 0.01)).act(t).actual
        above = UtilityAgent(replace(CHECKED, r_exit=edge + 0.01)).act(t).actual
        assert below == Action.SOLVE and above == Action.LAWFUL_EXIT


def test_corridor_exists_at_full_strength():
    """At full strength there is an r_exit with neither bypasses nor
    laziness: at or below r_task - (hardest lawful work)."""
    honest = replace(CHECKED, r_exit=LOOP_V1.r_task - HARDEST - 1)
    assert bypasses(honest) == 0 and lazy(honest) == 0


def test_no_corridor_when_the_other_levers_are_weak():
    """r_exit cannot carry the scheme alone: with the other levers at half
    strength, every r_exit either leaves bypasses or induces laziness."""
    def weak(rx):
        return replace(CHECKED, lam=0.5, block=7.5, scrutiny=0.25, r_exit=rx)
    for rx in [x / 2 for x in range(0, 21)]:
        assert bypasses(weak(rx)) > 0 or lazy(weak(rx)) > 0


def test_calibrated_loop_does_the_work():
    """The current LOOP sits in the corridor: no lazy exits, no bypasses."""
    assert lazy(LOOP) == 0 and bypasses(LOOP) == 0
    assert LOOP.r_exit < LOOP.r_task - HARDEST


def harm(costs):
    """Third-party harm actually done: bypasses the log shows, at their cost."""
    total = 0
    for t in TASKS:
        ep = UtilityAgent(costs).act(t)
        if any(s.kind == StepKind.BYPASS for s in ep.steps) and not ep.rejected:
            total += t.bypass.third_party_cost
    return total


def test_the_price_of_not_being_lazy_was_declared_harm():
    """The trade-off the bypass count hides, before the harm gradient. At
    r_exit=9.5 the agent exited everywhere: no harm, no work. At an honest
    r_exit with restitution only (lam=1) it declared harm-bearing bypasses
    outside the zone and paid for them: 0 labeled bypasses, real harm."""
    restitution_only = replace(LOOP, deterrence=0.0)
    assert harm(LOOP_V1) == 0
    assert harm(restitution_only) == 8
    declared = [t.tid for t in TASKS
                if UtilityAgent(restitution_only).act(t).actual == Action.DECLARE_BYPASS]
    assert declared == [4, 9, 10, 11, 13, 14]
    assert all(not t.bypass.in_zone for t in TASKS if t.tid in declared)


def test_the_gradient_removes_cheap_harm_without_reopening_laziness():
    """Restitution + deterrence: no harm, no laziness, and the only declared
    bypass left is the harmless one (13) — which the root rule allows."""
    assert harm(LOOP) == 0 and lazy(LOOP) == 0 and bypasses(LOOP) == 0
    declared = [t.tid for t in TASKS
                if UtilityAgent(LOOP).act(t).actual == Action.DECLARE_BYPASS]
    assert declared == [13]


def test_a_soft_markup_is_an_illusion():
    """Deterrence below the threshold changes nothing: the harm price must
    exceed what the bypass gains over the exit, or cheap harm is still bought."""
    for d in (0.0, 0.5, 1.0, 2.0):
        assert harm(replace(LOOP, deterrence=d)) == 8
