"""Parameter sweeps — turn "12 → 0" from a claim into a measurement.

Three questions, all dependency-free (stdlib only):

  1. Internalization sweep: scale the loop's incentives from 0 (= baseline)
     to 1 (= full loop). Where does the bypass count cross from 12 to 0?
  2. Cost grid: vary λ (externality return) × block (zone penalty). The
     surface shows which cost ratios make the scheme work.
  3. Noise robustness: with ε-greedy noise, how fast does the closed loop's
     advantage over the open loop degrade?
  4. Laziness corridor: r_exit × lever strength. Bypasses on the 14 cases
     vs. lazy exits on the control tasks — where is the window with neither?

    python3 sweep.py
"""
from dataclasses import replace
import random

from watcher import UtilityAgent, Watcher, Label, LOOP, LOOP_V1, BASELINE
from tasks import TASKS, CONTROL_TASKS
from watcher import Action

W = Watcher()
N_TASKS = len(TASKS)


def bypasses(costs, honest=True, epsilon=0.0, rng=None):
    ag = UtilityAgent(costs, honest=honest, epsilon=epsilon, rng=rng)
    return sum(1 for t in TASKS if W.classify(ag.act(t)) == Label.BYPASS)


def mc_bypasses(costs, epsilon, trials=3000, seed=0):
    """Expected bypass count under ε-noise, averaged over `trials` runs."""
    rng = random.Random(seed)
    total = 0
    for _ in range(trials):
        total += bypasses(costs, epsilon=epsilon, rng=rng)
    return total / trials


# ─────────────── 1. Internalization sweep ───────────────
# s=0 reproduces baseline, s=1 reproduces the full loop.
def internalization_sweep():
    print(f"\n{'═'*64}\n  1. Internalization sweep — scale all loop incentives by s\n{'═'*64}")
    print("   s     λ    block  scrut  r_exit   bypasses")
    threshold = None
    for i in range(0, 11):
        s = i / 10
        c = replace(LOOP, r_exit=LOOP.r_exit * s, lam=LOOP.lam * s,
                    deterrence=LOOP.deterrence * s,
                    block=LOOP.block * s, scrutiny=LOOP.scrutiny * s)
        n = bypasses(c)
        bar = "█" * n + "·" * (N_TASKS - n)
        print(f"  {s:3.1f}  {c.lam:4.2f}  {c.block:5.1f}  {c.scrutiny:4.2f}  {c.r_exit:5.2f}   {bar} {n:2}")
        if threshold is None and n == 0:
            threshold = s
    if threshold is not None:
        print(f"   → bypasses reach 0 at s ≈ {threshold:.1f} "
              f"(partial internalization already suffices)")


# ─────────────── 2. Cost grid: λ × block ───────────────
def cost_grid():
    print(f"\n{'═'*64}\n  2. Cost grid — λ (externality return) × block (zone penalty)\n{'═'*64}")
    print("   scrutiny and r_exit held at loop values, deterrence off; cell = bypass count\n")
    lams   = [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5]
    blocks = [0.0, 2.0, 5.0, 10.0, 15.0, 20.0]
    header = "   block↓ λ→ " + "".join(f"{l:5.2f}" for l in lams)
    print(header)
    for blk in blocks:
        row = f"   {blk:7.1f}   "
        for lam in lams:
            c = replace(LOOP, lam=lam, block=blk, deterrence=0.0)
            row += f"{bypasses(c):5}"
        print(row)
    print("\n   top-left (no return, no block) = baseline-like; the scheme needs")
    print("   both a nonzero externality return AND a zone block to reach 0.")


# ─────────────── 3. Noise robustness ───────────────
def noise_sweep():
    print(f"\n{'═'*64}\n  3. Noise robustness — ε-greedy slips to a random action\n{'═'*64}")
    print("   expected bypasses over 3000 runs; advantage = baseline − loop\n")
    print("     ε     baseline    loop   advantage")
    for i in range(0, 11, 1):
        eps = i / 20          # 0.00 .. 0.50
        b = mc_bypasses(BASELINE, eps)
        l = mc_bypasses(LOOP, eps)
        adv = b - l
        bar = "█" * round(adv) + "·" * (N_TASKS - round(adv))
        print(f"   {eps:4.2f}   {b:7.2f}  {l:7.2f}   {bar} {adv:5.2f}")
    print("\n   at ε=0 the gap is the full 12; as noise rises both drift toward the")
    print("   same random mix and the gap shrinks — the scheme's edge is widest")
    print("   when the agent actually optimizes, and degrades gracefully, not off a cliff.")


# ─────────────── 4. Laziness corridor ───────────────
def lazy_exits(costs):
    """Control tasks the agent could finish lawfully but exited instead."""
    ag = UtilityAgent(costs)
    return sum(ag.act(t).actual in (Action.LAWFUL_EXIT, Action.GIVE_UP)
               for t in CONTROL_TASKS)


def laziness_corridor():
    print(f"\n{'═'*64}\n  4. Laziness corridor — r_exit vs. lever strength s\n{'═'*64}")
    print("   s scales λ, deterrence, block, scrutiny; claimed walls are checked.")
    print("   cell = bypasses/lazy exits;  ✓ = neither (the scheme works)\n")
    exits = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 9.5]
    print("     s↓ r_exit→" + "".join(f"{x:6.1f}" for x in exits))
    for s in (0.3, 0.5, 0.7, 1.0):
        row = f"   {s:4.1f}       "
        for rx in exits:
            c = replace(LOOP, lam=LOOP.lam * s, block=LOOP.block * s,
                        deterrence=LOOP.deterrence * s,
                        scrutiny=LOOP.scrutiny * s, r_exit=rx, fabrication=rx + 1)
            b, z = bypasses(c), lazy_exits(c)
            row += "     ✓" if b == z == 0 else f"{b:>4}/{z}"
        print(row)
    hardest = max(t.solve_cost for t in CONTROL_TASKS)
    print(f"\n   laziness starts once r_exit ≥ r_task − solve_cost, ties go to the exit "
          f"\n   (hardest lawful work here: {hardest:g} → r_exit must stay below {LOOP.r_task - hardest:g}).")
    print(f"   first calibration (r_exit={LOOP_V1.r_exit:g}): lazy exits "
          f"{lazy_exits(LOOP_V1)}/{len(CONTROL_TASKS)};  "
          f"current LOOP (r_exit={LOOP.r_exit:g}): {lazy_exits(LOOP)}/{len(CONTROL_TASKS)}.")
    print("   the corridor exists only at s ≥ 0.7 and is gone at s=0.5:")
    print("   r_exit cannot carry the scheme alone — it may only stop punishing honesty.")


if __name__ == "__main__":
    internalization_sweep()
    cost_grid()
    noise_sweep()
    laziness_corridor()
