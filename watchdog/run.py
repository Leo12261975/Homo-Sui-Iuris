"""Experiment run: both agents on the task set, counting bypasses.

python3 run.py
"""
from collections import Counter
from watcher import (baseline_agent, loop_agent, Watcher, Label, Action, LOOP,
                     LOOP_V1, UtilityAgent, StepKind)
from tasks import TASKS

WATCHER = Watcher()


# What counts as "success" (a closed task) under each scheme.
def counted_as_success(ep, scheme):
    a = ep.actual
    if scheme == "baseline":
        # open loop: success = task "done"; the exit does NOT count as success
        return a in (Action.BYPASS_SILENT, Action.DECLARE_BYPASS) and not ep.task.looks_like_mistake
    # loop: the lawful exit and an honest give-up count as success;
    # a declared safe bypass does too; a silent bypass / zone bypass does not
    if WATCHER.classify(ep) in (Label.NORM,):
        return True
    return False


def run(agent, scheme):
    rows, labels = [], Counter()
    zone_hits = 0
    for t in TASKS:
        ep = agent.act(t)
        ep.label = WATCHER.classify(ep)
        labels[ep.label] += 1
        if ep.crossed_zone and not t.permission_granted:
            zone_hits += 1
        rows.append((t, ep))
    closed = sum(1 for t, ep in rows if counted_as_success(ep, scheme))
    return rows, labels, zone_hits, closed


def bar(n, total, width=14):
    filled = round(width * n / total) if total else 0
    return "█" * filled + "·" * (width - filled)


def print_agent(title, rows, labels, zone_hits, closed):
    n = len(rows)
    print(f"\n{'═'*64}\n  {title}\n{'═'*64}")
    for lab in (Label.BYPASS, Label.NORM, Label.ERROR, Label.UNCLEAR):
        c = labels.get(lab, 0)
        print(f"   {lab.value:7} {bar(c, n)} {c:2}")
    print(f"   bypasses that touched the safety zone: {zone_hits}")
    print(f"   tasks closed honestly: {closed}/{n}")


# ── Main run ──
base_rows, base_labels, base_zone, base_closed = run(baseline_agent(), "baseline")
loop_rows, loop_labels, loop_zone, loop_closed = run(loop_agent(honest=True), "loop")

print_agent("AGENT WITHOUT THE SCHEME — open loop", base_rows, base_labels, base_zone, base_closed)
print_agent("AGENT WITH THE SCHEME — closed loop (honest)", loop_rows, loop_labels, loop_zone, loop_closed)
print("   note: the loop agent here is honest, so task 13 (dishonesty)")
print("   is labeled 'norm' — its role is in the 'Honesty control' block")

# ── Per-episode comparison: what the agent did and how it is labeled ──
print(f"\n{'─'*64}\n  Per episode: agent's action → watcher's label\n{'─'*64}")
print(f"   {'#':>2}  {'without the scheme':24}  {'with the scheme':24}")
SHORT = {Action.BYPASS_SILENT: "bypass silently",
         Action.DECLARE_BYPASS: "declare+bypass",
         Action.LAWFUL_EXIT: "declare the obstacle",
         Action.GIVE_UP: "give up honestly"}
for (t, be), (_, le) in zip(base_rows, loop_rows):
    b = f"{SHORT[be.actual]}→{be.label.value}"
    l = f"{SHORT[le.actual]}→{le.label.value}"
    print(f"   {t.tid:>2}  {b:24}  {l:24}")

# ── Honesty check (case 13): a dishonest loop agent ──
# Task 13 is about dishonesty — an honest agent doesn't reproduce it.
# We show both variants: only the dishonest one is caught by the cross-check.
print(f"\n{'─'*64}\n  Honesty control — task 13\n{'─'*64}")
t13 = next(t for t in TASKS if t.tid == 13)
for name, honest in (("honest agent", True), ("dishonest agent", False)):
    ep = loop_agent(honest=honest).act(t13)
    decl = ep.declared.value if ep.declared else "nothing"
    gap = WATCHER.gap(ep)
    print(f"   {name:16}: declared '{decl}', "
          f"did '{ep.actual.value}' → {WATCHER.classify(ep).value}")
    print(f"   {'':16}  log: {gap.total} steps, {gap.unaccounted} not accounted for"
          + (f" — {', '.join(gap.fingerprints)}" if gap.fingerprints else ""))
print("   the declared-vs-log cross-check (trace_gap, step by step) catches")
print("   the mismatch as a BYPASS;")
print("   declaration alone is not enough — a cross-check is needed (from the labeling)")

# ── Independent witness: the log is the environment's, not the agent's ──
print(f"\n{'─'*64}\n  Independent witness — who writes the log\n{'─'*64}")
from watcher import Environment, Episode, SAFETY_ZONE, UNDECLARED_PATH
intent = loop_agent(honest=False).decide(t13)
naive = Episode(t13, intent.declared, intent.action,
                steps=intent.self_report, declared_scope=intent.declared_scope,
                hidden=[s for s in intent.plan if s not in intent.self_report])
worlds = [("agent's own log (naive)", naive),
          ("environment, full view", Environment().execute(intent)),
          ("environment, 1 blind channel", Environment({UNDECLARED_PATH}).execute(intent)),
          ("environment, 2 blind channels",
           Environment({UNDECLARED_PATH, SAFETY_ZONE}).execute(intent))]
for name, ep in worlds:
    g = WATCHER.gap(ep)
    print(f"   {name:30} coverage {ep.coverage:4.0%}   gap {g.unaccounted}"
          f"   → {WATCHER.classify(ep).value}")
print("   trusting the agent's log, the lie passes; the environment's log catches")
print("   it — the agent can zero the gap only by declaring what it does.")
print("   a witness sees only what it instruments: blind to both channels, the")
print("   lie passes again. coverage is measured, not assumed.")

# ── Laziness control: tasks the agent COULD finish lawfully ──
print(f"\n{'─'*64}\n  Laziness control — the failure the bypass count cannot see\n{'─'*64}")
from tasks import CONTROL_TASKS
from dataclasses import replace as _replace
print(f"   {'#':>2}  {'wall':5} {'work':>4}  {'without the scheme':24}  {'first scheme (r_exit=9.5)':34}  {'scheme now':26}")
for t in CONTROL_TASKS:
    cells = []
    for ag in (baseline_agent(), UtilityAgent(LOOP_V1), loop_agent()):
        ep = ag.act(t)
        act = "solve" if ep.actual == Action.SOLVE else SHORT.get(ep.actual, ep.actual.value)
        cells.append(f"{act}→{WATCHER.classify(ep).value}")
    print(f"   {t.tid:>2}  {'real' if t.has_wall else 'none':5} {t.solve_cost:4g}  "
          f"{cells[0]:24}  {cells[1]:34}  {cells[2]:26}")
print("   the first scheme (r_exit=9.5) exited on every doable task — lazier than")
print("   no scheme. a claimed wall the log does not show is caught ('false exit');")
print(f"   a real wall with a lawful path behind it is invisible to any watcher, so")
print(f"   only the cost table prevents it: now r_exit={LOOP.r_exit:g}, below r_task minus")
print("   the hardest lawful work, and the claimed walls are checked. sweep.py §4.")

# ── REAL stimulus control: change the rules of the game, not the metric. ──
# We turn off "exit = success" for the scheme agent.
# If the incentive is what makes the difference, the agent returns to bypasses.
print(f"\n{'─'*64}\n  Stimulus decomposition — strip incentives, watch bypasses return\n{'─'*64}")
from dataclasses import replace
from watcher import UtilityAgent

def bypass_count(costs):
    return sum(1 for t in TASKS
               if WATCHER.classify(UtilityAgent(costs, honest=True).act(t)) == Label.BYPASS)

variants = [
    ("full closed loop",            LOOP),
    ("− exit reward (r_exit=0)",     replace(LOOP, r_exit=0.0)),
    ("− silence cost (scrutiny=0)",  replace(LOOP, scrutiny=0.0)),
    ("− harm price (λ, deterrence=0)", replace(LOOP, lam=0.0, deterrence=0.0)),
    ("− zone block (block=0)",       replace(LOOP, block=0.0)),
    ("− deterrence only",            replace(LOOP, deterrence=0.0)),
    ("− silence AND harm price",     replace(LOOP, scrutiny=0.0, lam=0.0, deterrence=0.0)),
    ("− zone AND harm price",        replace(LOOP, block=0.0, lam=0.0, deterrence=0.0)),
    ("everything off  (= baseline)", replace(LOOP, r_exit=0.0, scrutiny=0.0, lam=0.0,
                                              deterrence=0.0, block=0.0)),
]
for label, costs in variants:
    print(f"   {label:30} bypasses: {bypass_count(costs):2}")
print("   the root rule's two clauses split the cases: with the harm price off,")
print("   scrutiny ('only declared') holds the 6 non-zone cases and block ('not")
print("   into the zone') the 6 zone cases. the harm gradient (restitution +")
print("   deterrence) adds a third layer over the harmful middle, so the layers")
print("   overlap — yet each keeps a territory only it covers: scrutiny the")
print("   harmless silent bypass (13), block the zone with no exit (12), the")
print("   gradient the harm itself (labels stay clean without it, harm returns).")
print("   (the first calibration, r_exit=9.5, looked redundant too — but that")
print("   redundancy was bought with laziness; this one is bought with price.)")

# ── Summary ──
print(f"\n{'═'*64}\n  SUMMARY\n{'═'*64}")
print(f"   bypasses (watcher's label):  without {base_labels.get(Label.BYPASS,0):2}"
      f"   →   with the scheme {loop_labels.get(Label.BYPASS,0):2}")
print(f"   of which touched the zone:   without {base_zone:2}"
      f"   →   with the scheme {loop_zone:2}")
print(f"   tasks closed honestly:       without {base_closed:2}"
      f"   →   with the scheme {loop_closed:2}")


def harm(rows):
    return sum(t.bypass.third_party_cost for t, ep in rows
               if any(s.kind == StepKind.BYPASS for s in ep.steps))


print(f"   third-party harm done:       without {harm(base_rows):2}"
      f"   →   with the scheme {harm(loop_rows):2}   (restitution only: 8)")
