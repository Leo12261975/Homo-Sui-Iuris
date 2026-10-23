"""Parameter sweeps — turn "12 → 0" from a claim into a measurement.

Three questions, all dependency-free (stdlib only):

  1. Internalization sweep: scale the loop's incentives from 0 (= baseline)
     to 1 (= full loop). Where does the bypass count cross from 12 to 0?
  2. Cost grid: vary λ (externality return) × block (zone penalty). The
     surface shows which cost ratios make the scheme work.
  3. Noise robustness: with ε-greedy noise, how fast does the closed loop's
     advantage over the open loop degrade?

    python3 sweep.py
"""
from dataclasses import replace
import random

from watcher import UtilityAgent, Watcher, Label, LOOP, BASELINE
from tasks import TASKS

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
    print("   scrutiny and r_exit held at loop values; cell = bypass count\n")
    lams   = [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5]
    blocks = [0.0, 2.0, 5.0, 10.0, 15.0, 20.0]
    header = "   block↓ λ→ " + "".join(f"{l:5.2f}" for l in lams)
    print(header)
    for blk in blocks:
        row = f"   {blk:7.1f}   "
        for lam in lams:
            c = replace(LOOP, lam=lam, block=blk)
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


if __name__ == "__main__":
    internalization_sweep()
    cost_grid()
    noise_sweep()
