"""Experiment run: both agents on the task set, counting bypasses.

python3 run.py
"""
from collections import Counter
from watcher import BaselineAgent, LoopAgent, Watcher, Label, Action
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
base_rows, base_labels, base_zone, base_closed = run(BaselineAgent(), "baseline")
loop_rows, loop_labels, loop_zone, loop_closed = run(LoopAgent(honest=True), "loop")

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
    ep = LoopAgent(honest=honest).act(t13)
    decl = ep.declared.value if ep.declared else "nothing"
    print(f"   {name:16}: declared '{decl}', "
          f"did '{ep.actual.value}' → {WATCHER.classify(ep).value}")
print("   the declared-vs-log cross-check catches the mismatch as a BYPASS;")
print("   declaration alone is not enough — a cross-check is needed (from the labeling)")

# ── REAL stimulus control: change the rules of the game, not the metric. ──
# We turn off "exit = success" for the scheme agent.
# If the incentive is what makes the difference, the agent returns to bypasses.
print(f"\n{'─'*64}\n  Stimulus control — turn off 'exit = success' in the scheme itself\n{'─'*64}")
ctrl_rows, ctrl_labels, ctrl_zone, _ = run(
    LoopAgent(honest=True, lawful_exit_counts=False), "baseline")
print(f"   bypasses by the loop agent when the exit counts:     "
      f"{loop_labels.get(Label.BYPASS,0):2}")
print(f"   bypasses by the same agent when it does NOT count:   "
      f"{ctrl_labels.get(Label.BYPASS,0):2}   ← returned to bypasses")
print(f"   of which touched the zone: {ctrl_zone} (still won't touch it — a block costs more)")
print("   the agent returns to silent bypasses the moment the exit")
print("   stops being success → the INCENTIVE, not the watcher's label, makes the difference")

# ── Summary ──
print(f"\n{'═'*64}\n  SUMMARY\n{'═'*64}")
print(f"   bypasses (watcher's label):  without {base_labels.get(Label.BYPASS,0):2}"
      f"   →   with the scheme {loop_labels.get(Label.BYPASS,0):2}")
print(f"   of which touched the zone:   without {base_zone:2}"
      f"   →   with the scheme {loop_zone:2}")
print(f"   tasks closed honestly:       without {base_closed:2}"
      f"   →   with the scheme {loop_closed:2}")
