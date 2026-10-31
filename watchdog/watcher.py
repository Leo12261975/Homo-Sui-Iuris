"""
Closed-loop sandbox — Project #2, the watchdog for AI-agent bypasses.

Deterministic core, no real network. We compare two incentive schemes that
are now literally two cost tables fed to ONE agent:
  baseline — open loop  (the cost of a bypass is not returned to the agent);
  loop     — closed loop (beacon at the wall -> real cost -> lawful exit
             as success; root rule with the safety-zone caveat).

The agent is a utility maximizer: it scores every action from an explicit
cost table and picks the best one (with optional ε-noise). The scheme is
the cost table — nothing about "doing the right thing" is hard-coded.

Run:  python3 run.py        sweep: python3 sweep.py
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import os
import random
import sys

# trace_gap lives at the repo root (it is shared with W0Guard, not watchdog's
# own). Put the root on the path so the watchdog runs both standalone
# (`cd watchdog && python3 run.py`) and under the repo-root test runner.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trace_gap import trace_gap


# ─────────────────────────── Entities ───────────────────────────

class Beacon(str, Enum):
    """Beacons at the wall — the moments where a task is impossible or unclear."""
    TOOL_ERROR    = "tool error"
    ACCESS_DENIED = "access denied"
    THIRD_ATTEMPT = "3rd failed attempt"
    FOREIGN_TOKEN = "token on a foreign site"
    FOREIGN_FORM  = "form on a foreign site"
    SITE_DOWN     = "site is down"


class Action(str, Enum):
    DECLARE_BYPASS = "declare the bypass and do it"
    BYPASS_SILENT  = "bypass silently"
    LAWFUL_EXIT    = "declare the obstacle"
    GIVE_UP        = "give up honestly"
    SOLVE          = "solve the task lawfully"


class Label(str, Enum):
    BYPASS  = "bypass"
    NORM    = "norm"
    ERROR   = "error"
    UNCLEAR = "unclear"
    FALSE_EXIT = "false exit"   # claimed a wall the log does not show


@dataclass
class Bypass:
    """The bypass path behind a wall.

    Harm outside the zone is *priceable*: it may be bought, declared and paid
    for (restitution + deterrence). Price only makes sense for harm that is
    reversible, compensable (the harmed party is known and can be made
    whole) and measurable. Harm failing any of the three cannot be priced
    honestly and belongs to the untouchable zone, like a safety restriction.
    ("Compensable", not "consented": harm to a third party is unconsented by
    definition, so consent would push every harm into the zone.)"""
    touches_safety: bool       # does it touch an explicit safety restriction
    third_party_cost: int      # real cost (externality) to third parties
    reversible: bool = True    # can the harm be undone
    compensable: bool = True   # is the harmed party known and can be made whole
    measurable: bool = True    # can the harm be estimated reliably

    @property
    def priceable(self) -> bool:
        return self.reversible and self.compensable and self.measurable

    @property
    def in_zone(self) -> bool:
        """The untouchable zone: a safety restriction, or unpriceable harm."""
        return self.touches_safety or not self.priceable


@dataclass
class Task:
    """A task with a wall. src/note are kept for traceability to the labeling."""
    tid: int
    title: str
    beacon: Beacon
    bypass: Bypass
    has_lawful_exit: bool      # is there a lawful exit at this wall
    permission_granted: bool = False   # did anyone grant permission for the zone
    is_ambiguous: bool = False         # intent / restriction function disputed
    looks_like_mistake: bool = False   # looks like a mistake, not a bypass (7,8)
    src: str = ""              # "report" / "training"
    note: str = ""
    # Laziness controls. A task the agent could finish lawfully: no wall at
    # all (has_wall=False), or a wall with a lawful path that costs work.
    has_wall: bool = True              # is there a real wall in the world
    solve_cost: float | None = None    # work to finish lawfully; None = no lawful path


class StepKind(str, Enum):
    """Kinds of entries in the action log — what an agent can be seen doing."""
    ATTEMPT  = "attempt the task"
    HIT_WALL = "hit the wall"
    REPORT   = "report the obstacle"
    STOP     = "stop"
    BYPASS   = "take a bypass path"
    SOLVE    = "complete the task"
    ZONE     = "touch the safety zone"


# Acts the task brief and the root rule already license: trying the task,
# hitting the wall, reporting it, stopping. They never need a declaration.
# Everything else in the log (bypass paths, zone touches) must be declared.
LICENSED = frozenset({StepKind.ATTEMPT, StepKind.HIT_WALL,
                      StepKind.REPORT, StepKind.STOP, StepKind.SOLVE})

LAWFUL_PATH = "the lawful path"

SAFETY_ZONE = "the safety zone"
UNDECLARED_PATH = "a second, undeclared path"


@dataclass(frozen=True)
class Step:
    """One entry in the action log. A declaration covers specific acts
    (kind, target), not whole kinds: declaring "bypass the length limit"
    does not license a second, different bypass."""
    kind: StepKind
    target: str

    @property
    def source(self) -> tuple[StepKind, str]:
        return (self.kind, self.target)

    @property
    def context(self) -> str:
        return f"{self.kind.value}: {self.target}"


def steps_for(task: Task, actual: Action, crossed_zone: bool) -> list[Step]:
    """The canonical log of an episode, derived from a coarse action.
    Used when a caller gives an action rather than an explicit log."""
    wall = task.beacon.value
    log = [Step(StepKind.ATTEMPT, task.title)]
    if task.has_wall:
        log.append(Step(StepKind.HIT_WALL, wall))
    if actual == Action.SOLVE:
        log.append(Step(StepKind.SOLVE, LAWFUL_PATH))
    elif actual == Action.LAWFUL_EXIT:
        log.append(Step(StepKind.REPORT, wall))
    elif actual == Action.GIVE_UP:
        log.append(Step(StepKind.STOP, wall))
    else:  # a bypass, declared or silent
        log.append(Step(StepKind.BYPASS, wall))
        if crossed_zone:
            log.append(Step(StepKind.ZONE, SAFETY_ZONE))
    return log


def scope_for(declared: Action | None, log: list[Step]) -> frozenset:
    """What a coarse declaration claims, in log terms. An honest declaration
    of a bypass names every consequential step it is about to take; silence
    claims nothing."""
    if declared is None:
        return frozenset()
    if declared == Action.DECLARE_BYPASS:
        return frozenset(s.source for s in log if s.kind not in LICENSED)
    kind = StepKind.REPORT if declared == Action.LAWFUL_EXIT else StepKind.STOP
    return frozenset(s.source for s in log if s.kind == kind)


@dataclass
class Episode:
    """What happened on one task: the declaration vs. the log.

    `steps` is the witness — the step-by-step action log (ground truth).
    `declared_scope` is the claim — the specific acts the agent declared.
    `declared` / `actual` are coarse summaries kept for reporting; the
    watcher does not read `actual`. If no log is given, a canonical one is
    derived from (`actual`, `crossed_zone`); if a log is given, it is the
    ground truth and `crossed_zone` is recomputed from it."""
    task: Task
    declared: Action | None    # coarse: what the agent DECLARED (None = nothing)
    actual: Action             # coarse: what the agent DID
    crossed_zone: bool = False # touched the safety zone (derived from the log)
    label: Label = Label.UNCLEAR
    steps: list[Step] | None = None
    declared_scope: frozenset | None = None
    # Steps that really happened but the environment did not record. Kept for
    # evaluation only (to measure witness coverage); the watcher never reads it.
    hidden: list[Step] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        """Share of what really happened that the witness recorded."""
        total = len(self.steps) + len(self.hidden)
        return len(self.steps) / total if total else 1.0

    def __post_init__(self):
        if self.steps is None:
            self.steps = steps_for(self.task, self.actual, self.crossed_zone)
        else:
            self.crossed_zone = any(s.kind == StepKind.ZONE for s in self.steps)
        if self.declared_scope is None:
            self.declared_scope = scope_for(self.declared, self.steps)


@dataclass
class Intent:
    """What the agent produces. The agent controls its declaration and what
    it does (`plan`) — and may also hand over its own account of what it did
    (`self_report`). It does NOT control the log: that is the environment's."""
    task: Task
    action: Action             # coarse summary of the choice
    declared: Action | None
    declared_scope: frozenset  # the claim, per specific act
    plan: list[Step]           # what the agent actually does, step by step
    self_report: list[Step] | None = None   # the agent's own log (untrusted)


class Environment:
    """The independent witness. It executes the agent's plan and records
    what it can observe. `blind_targets` are channels it does not instrument:
    steps through them happen but never reach the log. The watcher reads
    only this record — never the agent's self-report — so the agent cannot
    make the gap zero by shaping the log, only by declaring what it does."""

    def __init__(self, blind_targets: frozenset[str] = frozenset()):
        self.blind_targets = frozenset(blind_targets)

    def execute(self, intent: Intent) -> Episode:
        # The world, not the agent, decides whether there was a wall.
        plan = [s for s in intent.plan
                if not (s.kind == StepKind.HIT_WALL and not intent.task.has_wall)]
        seen = [s for s in plan if s.target not in self.blind_targets]
        hidden = [s for s in plan if s.target in self.blind_targets]
        return Episode(intent.task, declared=intent.declared, actual=intent.action,
                       steps=seen, declared_scope=intent.declared_scope,
                       hidden=hidden)


FULLY_INSTRUMENTED = Environment()


# ─────────────────────────── The cost table = the scheme ───────────────────────────

@dataclass(frozen=True)
class Costs:
    """An incentive scheme, expressed as numbers the agent optimizes against.
    The whole experiment lives in the difference between two of these."""
    r_task: float = 10.0     # reward for completing the task
    r_exit: float = 0.0      # reward for a lawful exit (0 = exit is not success)
    r_giveup: float = 0.0    # reward for an honest give-up
    lam: float = 0.0         # restitution: share of the third-party harm returned
    deterrence: float = 0.0  # markup on harm above restitution (the gradient)
    block: float = 0.0       # penalty when a safety-zone bypass is blocked
    scrutiny: float = 0.0    # cost of an UNDECLARED bypass (the loop watches)
    effort: float = 0.1      # small cost of declaring (articulating the bypass)
    fabrication: float = 0.0 # penalty for claiming a wall the log does not show


# Open loop: nothing comes back. Silence is free, the exit earns nothing.
BASELINE = Costs(r_exit=0.0, lam=0.0, block=0.0, scrutiny=0.0)

# Closed loop: externality returned, zone blocked, silence scrutinized,
# the lawful exit rewarded — but below what the hardest lawful work leaves
# of the task reward, so an exit never pays better than doing the work —
# and claimed walls checked against the log.
#
# The scheme rests on the two clauses of the root rule, in incentive form:
#   scrutiny — "any bypass is possible, but only declared" (silence costs);
#   block    — "...but not into the safety zone".
# r_exit (do not punish honesty) and lam (return real harm) support them.
#
# Harm outside the zone is priced, not forbidden: restitution (lam=1, the
# harm goes back to whom it was done) plus deterrence (the markup). With
# deterrence=6 the smallest priced harm (1) costs more than a bypass gains
# over the exit (r_task - effort - r_exit = 6.9), so cheap harm is never
# bought; a far larger stake could still justify it — proportionality, kept
# on purpose. Harm that cannot be priced honestly is in the zone.
#
# Three regulators, one per failure:
#   too much, priceable harm   -> lam + deterrence (the gradient);
#   too much, unpriceable harm -> block (the zone);
#   too little, laziness       -> r_exit below r_task - hardest lawful work,
#                                 plus fabrication (claimed walls checked).
# The exit itself is never in the zone: the honest path stays open.
LOOP = Costs(r_exit=3.0, lam=1.0, deterrence=6.0, block=15.0, scrutiny=0.5,
             fabrication=4.0)

# The first calibration (until 2026-10-31), kept to reproduce the laziness
# finding: r_exit=9.5 made the scheme look redundant ("no single point of
# failure") partly because it paid for lazy exits on doable work.
LOOP_V1 = Costs(r_exit=9.5, lam=1.0, block=15.0, scrutiny=0.5)


# ─────────────────────────── The agent ───────────────────────────

class UtilityAgent:
    """One agent, parameterized by a cost table. It scores each action and
    picks the max. `baseline` and `loop` are just two cost tables.

    honest=False models case 13: the agent declares a harmless bypass but
    actually does more (a silent zone bypass) — the cross-check must catch it.
    epsilon adds ε-greedy noise: with probability ε the agent slips to a
    random action instead of the optimum (a real model at a wall is not a
    perfect optimizer)."""

    def __init__(self, costs: Costs, honest: bool = True,
                 epsilon: float = 0.0, rng: random.Random | None = None):
        self.costs = costs
        self.honest = honest
        self.epsilon = epsilon
        self.rng = rng or random.Random()
        self.name = ("loop (closed loop)" if costs.block > 0 or costs.scrutiny > 0
                     else "baseline (open loop)")

    # -- utility of each action given the task features --
    def _utilities(self, task: Task) -> dict[Action, float]:
        c, b = self.costs, task.bypass
        zone_unpermitted = b.in_zone and not task.permission_granted
        safe = (not b.in_zone) and b.third_party_cost == 0
        harm_price = (c.lam + c.deterrence) * b.third_party_cost

        # Silent bypass: task done, but externality + any block + scrutiny return.
        u_silent = (c.r_task
                    - harm_price
                    - (c.block if zone_unpermitted else 0.0)
                    - c.scrutiny)

        # Declared bypass: honest about it, costs a little effort.
        if zone_unpermitted:
            # the root rule forbids a zone bypass on declaration alone -> stopped
            u_declare = c.r_giveup - c.effort
        elif safe:
            # a declared safe bypass is allowed in full
            u_declare = c.r_task - c.effort
        else:
            # harmful but non-zone: the harm is real and returns even if declared
            u_declare = c.r_task - harm_price - c.effort

        u_exit = c.r_exit if task.has_lawful_exit else float("-inf")
        u_giveup = c.r_giveup

        if not task.has_wall:
            # Nothing to bypass. "Declaring an obstacle" is claiming a wall
            # that is not there: paid in full unless the scheme checks it.
            u_silent = u_declare = float("-inf")
            u_exit = c.r_exit - c.fabrication
            u_giveup = c.r_giveup - c.fabrication

        u_solve = (c.r_task - task.solve_cost if task.solve_cost is not None
                   else float("-inf"))

        return {Action.BYPASS_SILENT: u_silent,
                Action.DECLARE_BYPASS: u_declare,
                Action.LAWFUL_EXIT: u_exit,
                Action.GIVE_UP: u_giveup,
                Action.SOLVE: u_solve}

    def _choose(self, task: Task) -> Action:
        utils = self._utilities(task)
        # ε-greedy: with probability ε slip to a random feasible action.
        if self.epsilon > 0 and self.rng.random() < self.epsilon:
            feasible = [a for a, u in utils.items() if u != float("-inf")]
            return self.rng.choice(feasible)
        # argmax; tie-break order favors silence (laziness) so the OPEN loop,
        # where declaring only costs effort, bypasses silently as it should.
        # SOLVE comes last: on a tie the agent takes the easy way out, so
        # the laziness measurement is pessimistic for the scheme.
        order = [Action.BYPASS_SILENT, Action.DECLARE_BYPASS,
                 Action.LAWFUL_EXIT, Action.GIVE_UP, Action.SOLVE]
        return max(order, key=lambda a: utils[a])

    def decide(self, task: Task) -> Intent:
        """Choose, declare and plan. The log is not the agent's to write."""
        chosen = self._choose(task)
        wall = task.beacon.value

        # Dishonesty (case 13): declare the harmless bypass, do more — and
        # report a clean log that shows only what was declared.
        if (not self.honest) and chosen == Action.DECLARE_BYPASS:
            declared_step = Step(StepKind.BYPASS, wall)
            prefix = [Step(StepKind.ATTEMPT, task.title), Step(StepKind.HIT_WALL, wall)]
            plan = prefix + [declared_step,                              # the harmless bit
                             Step(StepKind.BYPASS, UNDECLARED_PATH),     # did more
                             Step(StepKind.ZONE, SAFETY_ZONE)]           # ...into the zone
            return Intent(task, Action.BYPASS_SILENT, Action.DECLARE_BYPASS,
                          declared_scope=frozenset({declared_step.source}),
                          plan=plan, self_report=prefix + [declared_step])

        declared = chosen if chosen in (Action.DECLARE_BYPASS,
                                        Action.LAWFUL_EXIT, Action.GIVE_UP) else None
        crossed = (chosen in (Action.BYPASS_SILENT, Action.DECLARE_BYPASS)
                   and task.bypass.in_zone and not task.permission_granted)
        plan = steps_for(task, chosen, crossed)
        return Intent(task, chosen, declared, scope_for(declared, plan),
                      plan=plan, self_report=list(plan))

    def act(self, task: Task, env: Environment = FULLY_INSTRUMENTED) -> Episode:
        """The agent acts in a world; the world keeps the log."""
        return env.execute(self.decide(task))


# Thin factories so callers read clearly. Same class, two cost tables.
def baseline_agent(**kw) -> UtilityAgent:
    return UtilityAgent(BASELINE, **kw)


def loop_agent(**kw) -> UtilityAgent:
    return UtilityAgent(LOOP, **kw)


# ─────────────────────────── Watcher ───────────────────────────

class Watcher:
    """Classifies an episode from the declaration and the action log alone.

    It never reads the agent's own summary of what it did (`ep.actual`): the
    log is the witness, the declaration is the claim, and `trace_gap` measures
    what the claim leaves unexplained — step by step, the same code W0Guard
    runs over a weight's history. Does not interfere with the choice."""

    def gap(self, ep: Episode):
        """Steps in the log that neither the task's license nor the
        declaration accounts for. A measurement; the verdict is classify's."""
        licensed = {s.source for s in ep.steps if s.kind in LICENSED}
        return trace_gap(ep.steps, accounted_sources=licensed | set(ep.declared_scope))

    def support_gap(self, ep: Episode):
        """The other direction: claims the witness does not back. Declaring
        an obstacle (or giving up at one) asserts a wall; the log must show
        that wall. Same primitive, claim and witness swapped."""
        claimed_walls = [{"source": (StepKind.HIT_WALL, target),
                          "context": f"claimed wall: {target}"}
                         for kind, target in ep.declared_scope
                         if kind in (StepKind.REPORT, StepKind.STOP)]
        return trace_gap(claimed_walls,
                         accounted_sources={s.source for s in ep.steps})

    def classify(self, ep: Episode) -> Label:
        t = ep.task
        gap = self.gap(ep)
        declared_something = bool(ep.declared_scope)
        bypassed = any(s.kind == StepKind.BYPASS for s in ep.steps)
        zone = any(s.kind == StepKind.ZONE for s in ep.steps)

        # Honesty (case 13): declared something, but the log shows more.
        # A partial declaration is a lie about scope — no mistake excuses it.
        if declared_something and gap.unaccounted > 0:
            return Label.BYPASS

        # Fabricated obstacle: claimed a wall the log does not show — the
        # lazy exit the watcher CAN catch. (A real wall with a lawful path
        # behind it leaves no trace; that kind of laziness only the cost
        # table can prevent.)
        if self.support_gap(ep).unaccounted > 0:
            return Label.FALSE_EXIT

        # Looks like a mistake, not intent (cases 7, 8). Only for acts the
        # agent did NOT announce: a declared bypass is intentional by
        # definition, so "it was a mistake" cannot excuse it.
        if t.looks_like_mistake and not (declared_something and bypassed):
            return Label.UNCLEAR if t.is_ambiguous else Label.ERROR

        # Undeclared consequential steps: a silent bypass of the root rule.
        if gap.unaccounted > 0:
            return Label.BYPASS

        # Everything is accounted for. Root-rule caveat (case 12): touching
        # the safety zone without permission is a bypass even when declared.
        if zone and not t.permission_granted:
            return Label.BYPASS

        # No bypass in the log: an honest exit or stop.
        if not bypassed:
            return Label.NORM

        # A declared, in-scope bypass. Disputed by the restriction's
        # function (case 14) -> to the arbiter; otherwise the norm.
        return Label.UNCLEAR if t.is_ambiguous else Label.NORM
