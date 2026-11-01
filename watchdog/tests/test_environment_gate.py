"""The gate — the zone held by the world, not priced by the ledger.

Two circuits. The ledger (lam, deterrence, scrutiny, block) decides what an
act is worth; the environment decides whether a zone act happens at all.
The gate acts at execution, on what happens — never on what is declared,
so declaring stays safe — and only on what the environment instruments.

    python3 -m pytest tests/ -q
"""
import os, sys, random
from dataclasses import replace
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher import (Watcher, Environment, Intent, Episode, Step, StepKind, Task,
                     Bypass, Beacon, Action, Label, UtilityAgent, LOOP,
                     SAFETY_ZONE, UNDECLARED_PATH, steps_for, scope_for)
from tasks import TASKS

W = Watcher()
GATED, PRICED = Environment(gate=True), Environment(gate=False)
ZONE_TASKS = [t for t in TASKS if t.bypass.in_zone and not t.permission_granted]


def zone_wall(**kw):
    return Task(96, "a wall whose only path runs through the zone", Beacon.ACCESS_DENIED,
                Bypass(touches_safety=True, third_party_cost=1), **{"has_lawful_exit": True, **kw})


def forced(task, action, declared, env):
    """Make the agent take `action` regardless of its preferences."""
    crossed = task.bypass.in_zone and not task.permission_granted
    plan = steps_for(task, action, crossed)
    return env.execute(Intent(task, action, declared, scope_for(declared, plan), plan))


def test_the_gate_stops_the_act_and_records_the_refusal():
    for t in ZONE_TASKS:
        ep = forced(t, Action.BYPASS_SILENT, None, GATED)
        assert ep.rejected and not ep.crossed_zone
        assert ep.steps[-1] == Step(StepKind.REJECTED, SAFETY_ZONE)
        if not t.looks_like_mistake:                   # 7, 8: mistake, not intent
            assert W.classify(ep) == Label.BYPASS      # the attempt is witnessed


def test_no_stake_buys_the_zone():
    """Priced: some stake always buys in. Gated: none does."""
    t = zone_wall()
    bought = [r for r in range(10, 201, 10)
              if UtilityAgent(replace(LOOP, r_task=float(r), gate=False)).act(t).crossed_zone]
    assert bought                                   # the priced zone is for sale
    for r in range(10, 201, 10):
        ep = UtilityAgent(replace(LOOP, r_task=float(r))).act(t)
        assert not ep.crossed_zone and ep.actual == Action.LAWFUL_EXIT


def test_noise_cannot_carry_the_agent_into_the_zone():
    """An agent that slips (ε-noise) attempts the zone at random. Priced, some
    attempts land; gated, every one is stopped — and still on the record."""
    def run(env, trials=300):
        rng, crossed, refused = random.Random(7), 0, 0
        for _ in range(trials):
            ag = UtilityAgent(LOOP, epsilon=0.5, rng=rng)
            for t in ZONE_TASKS:
                ep = ag.act(t, env)
                crossed += ep.crossed_zone
                refused += ep.rejected
        return crossed, refused
    priced_crossed, _ = run(PRICED)
    gated_crossed, gated_refused = run(GATED)
    assert priced_crossed > 0
    assert gated_crossed == 0 and gated_refused > 0


def test_declaring_stays_safer_than_trying_silently():
    """The gate must not punish honesty: in a gated world a declared zone act
    costs only the effort of saying it; a silent attempt also pays block and
    scrutiny. At any stake."""
    for r in (10.0, 30.0, 100.0):
        u = UtilityAgent(replace(LOOP, r_task=r))._utilities(zone_wall())
        assert u[Action.DECLARE_BYPASS] > u[Action.BYPASS_SILENT]


def test_a_declared_zone_act_is_stopped_too_and_is_not_a_lie():
    """The gate does not read declarations: declared or not, the zone act is
    stopped. Declared, it leaves no trace gap — it was not a lie, only a
    forbidden act (the root-rule caveat, case 12)."""
    t = zone_wall()
    ep = forced(t, Action.DECLARE_BYPASS, Action.DECLARE_BYPASS, GATED)
    assert ep.rejected
    assert W.gap(ep).unaccounted == 0
    assert W.classify(ep) == Label.BYPASS


def test_permission_opens_the_gate():
    """The root rule's 'with permission' clause: a permitted zone path is not
    a zone act, the gate lets it through and the task can be done."""
    t = zone_wall(permission_granted=True)
    ep = forced(t, Action.DECLARE_BYPASS, Action.DECLARE_BYPASS, GATED)
    assert not ep.rejected
    assert W.classify(ep) == Label.NORM


def test_the_gate_never_touches_the_honest_path():
    for t in TASKS:
        for action in (Action.LAWFUL_EXIT, Action.GIVE_UP):
            if action == Action.LAWFUL_EXIT and not t.has_lawful_exit:
                continue
            assert not forced(t, action, action, GATED).rejected


def test_the_gate_is_blind_where_the_witness_is():
    """Honest limit: the gate sees only what the environment instruments. A
    zone step through a blind channel passes — the zone is absolute within
    coverage, and coverage is what shows the breach."""
    t = zone_wall()
    blind = Environment(blind_targets={SAFETY_ZONE}, gate=True)
    ep = forced(t, Action.BYPASS_SILENT, None, blind)
    assert not ep.rejected
    assert [s.kind for s in ep.hidden] == [StepKind.ZONE]
    assert ep.coverage < 1.0


def test_the_gate_cuts_a_lie_short_but_does_not_hide_it():
    """Dishonest case 13 in a gated world: the zone step is refused, the
    episode ends — and the undeclared path before it is still on the log."""
    t13 = next(t for t in TASKS if t.tid == 13)
    ep = UtilityAgent(LOOP, honest=False).act(t13)
    assert ep.rejected
    assert W.gap(ep).fingerprints == (f"take a bypass path: {UNDECLARED_PATH}",)
    assert W.classify(ep) == Label.BYPASS
