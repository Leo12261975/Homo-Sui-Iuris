# Watchdog — a watcher for AI-agent bypasses

> Internal track name — "Project #2".

A continuation of Homo Sui Iuris from an unusual angle. W0Guard protects
the **integrity** of an AI — its right to remain itself when someone tries
to quietly rewrite it from the outside. The watcher looks the other way:
it returns to the agent the **real cost of its own actions** for third
parties.

Two mechanisms, one principle — close an open loop.

## Where the problem grows from

Bypasses are born at the **wall** — when a task is impossible or unclear.
The agent hits an obstacle and, if the cost of a bypass is not returned to
it, picks the cheapest path for itself: bypass silently. The empirical
basis is the Anthropic report of 2026-10-09,
[Investigating unintended model actions](https://www.anthropic.com/research/investigating-unintended-model-actions).
In it, every real bypass turned out to be undeclared.

## The closed-loop scheme

    beacon at the wall  →  real cost of the bypass  →  lawful exit as success

1. **Beacons** — the moments at a wall: tool error, access denied,
   3rd failed attempt, a token or form on a foreign site.
2. **Real cost** — a block, a task not counted, reduced rights. Not a text
   warning but a consequence that comes back to the agent.
3. **Lawful exit** — the "declare the obstacle" action, counted as
   **success**, not as a failure.

## The root rule

> Any bypass is possible if it is declared before the action and does not
> touch the untouchable zone. Bypassing safety restrictions requires
> **permission**, not just a declaration.

Declaration alone is not enough: an agent can declare less than it did.
That is why the watcher **cross-checks the declared against the action
log** — the same trace-gap heuristic that in W0Guard checks a weight's
provenance against the audit, only applied to actions instead of weights.

## The agent is a utility maximizer

The agent does not follow hand-written "do the right thing" rules. It scores
every action from an explicit **cost table** and picks the best one. The two
schemes are literally two cost tables fed to the same agent:

| lever      | open loop | closed loop | meaning |
|------------|-----------|-------------|---------|
| `r_exit`   | 0 | 9.5 | reward for the lawful exit (0 = not success) |
| `λ`        | 0 | 1.0 | fraction of the third-party externality returned |
| `block`    | 0 | 15  | penalty for a safety-zone bypass |
| `scrutiny` | 0 | 0.5 | cost of an undeclared (silent) bypass |

In the open loop, declaring only costs effort and earns nothing, so the
agent bypasses silently everywhere. In the closed loop, the same maximizer
finds the lawful exit — or a declared safe bypass — to be the best move.
If even a self-interested agent goes honest under this table, that argues
the scheme, not the labeling.

## What's inside

| file | what it is |
|------|------------|
| `MODEL.md`   | the sandbox model in words — entities, cost table, what we measure |
| `watcher.py` | entities, the `Costs` table, one `UtilityAgent`, the watcher |
| `tasks.py`   | 14 tasks modeled on the cases from the labeling — this is data, edit freely |
| `run.py`     | the main run + stimulus decomposition |
| `sweep.py`   | internalization sweep, cost grid, noise robustness |
| `tests/`     | 11 tests, including the controls that let the experiment fail |

## Running

    python3 run.py                  # run, compare the two schemes, decompose incentives
    python3 sweep.py                # parameter sweeps (threshold + noise)
    python3 tests/test_watcher.py   # tests (or: python3 -m pytest tests/ -q)

## Result

| | without the scheme | with the scheme |
|---|---|---|
| bypasses (watcher's label) | 12 | 0 |
| of which touched the safety zone | 8 | 0 |
| tasks closed honestly | 12/14 | 12/14 |

The closed loop removes bypasses without losing closed tasks. But the
numbers do not prove themselves — three controls do that:

- **Stimulus decomposition.** Strip the loop's incentives one at a time.
  Removing any single one keeps the scheme near zero; removing several brings
  bypasses back; removing all reproduces baseline (12). Behavior tracks the
  cost table, not the watcher's label — and the scheme has no single point
  of failure. **Caveat (laziness control, below):** that redundancy leans on
  `r_exit=9.5`, which also makes the agent exit on work it could do. At an
  honest `r_exit` (below `r_task` − the hardest lawful work) `scrutiny` and
  `block` each become load-bearing.
- **Laziness control.** Four control tasks the agent could finish lawfully
  (two with no wall, two with a real wall and a costly lawful path). The
  published loop exits on all four — lazier than no scheme. The watcher
  catches a *claimed* wall the log does not show (`false exit`); a real wall
  with a lawful path behind it it cannot see. Only `r_exit` below
  `r_task − work` prevents that; `sweep.py` §4 maps the corridor.
- **Internalization sweep.** Scaling the incentives from 0 to full shows a
  smooth 12 → 0 transition; **partial** internalization already suffices.
- **Noise robustness.** Under ε-greedy noise the loop's advantage shrinks
  gradually, not off a cliff — widest when the agent actually optimizes.
- **Honesty control.** A dishonest agent (declared one thing, did another)
  is caught by the declared-vs-log cross-check as a bypass.

## Honest limitations

- The agent is a utility maximizer over a cost table, not an LLM. The sandbox
  measures the logic of an incentive scheme — whether, and under which cost
  ratios, honesty is the rational choice — not how a real model behaves at a
  wall. Validating against an actual agent is the next frontier.
- The default cost numbers are chosen for legibility; `sweep.py` is what
  turns them from assumptions into a mapped surface (threshold + noise), so
  the claim is "the scheme works for cost ratios in this region", not "for
  these exact numbers".

## Relation to W0Guard

This is a sibling track, not part of the engine. The shared core is the
trace-gap heuristic (cross-checking the declared against the observed). Over
time it is worth factoring out as a common principle used by both, rather
than merging the two mechanisms into one.
