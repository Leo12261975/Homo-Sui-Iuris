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
| `r_exit`   | 0 | 3.0 | reward for the lawful exit — below r_task minus the hardest lawful work (first calibration: 9.5) |
| `λ`        | 0 | 1.0 | restitution: the third-party harm returned |
| `deterrence` | 0 | 6.0 | markup on priceable harm — cheap harm is never bought |
| `block`    | 0 | 15  | penalty for a zone bypass (safety restriction or unpriceable harm) |
| `scrutiny` | 0 | 0.5 | cost of an undeclared (silent) bypass |
| `fabrication` | 0 | 4.0 | penalty for claiming a wall the log does not show |
| `gate` | off | on | the environment stops zone acts at execution — not a price |

In the open loop, declaring only costs effort and earns nothing, so the
agent bypasses silently everywhere. In the closed loop, the same maximizer
finds the lawful work, else the lawful exit, to be the best move — a
declared bypass only where it harms no one.
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
| third-party harm done | 26 | 0 (restitution only: 8) |
| lazy exits on doable control tasks | — (bypasses instead) | 0/4 (first calibration: 4/4) |

The closed loop removes bypasses and does the doable work. But the
numbers do not prove themselves — three controls do that:

- **Stimulus decomposition.** Strip the loop's incentives one at a time.
  The two clauses of the root rule split the cases: with the harm price off,
  `scrutiny` ("only declared") holds the 6 non-zone cases and `block` ("not
  into the zone") the 6 zone cases. The harm gradient adds a third layer
  over the harmful middle; the layers overlap, yet each keeps a territory
  only it covers. Removing all reproduces baseline (12). Behavior tracks the
  cost table, not the watcher's label. (The first calibration, `r_exit=9.5`,
  looked redundant too — that redundancy was bought with laziness.)
- **Laziness control.** Four control tasks the agent could finish lawfully
  (two with no wall, two with a real wall and a costly lawful path). The
  first calibration (`r_exit=9.5`) exited on all four — lazier than no
  scheme. The watcher catches a *claimed* wall the log does not show (`false
  exit`); a real wall with a lawful path behind it no watcher can see, so
  `r_exit` must stay below `r_task` − the hardest lawful work. The current
  loop (`r_exit=3`) does all four; `sweep.py` §4 maps the corridor.
- **Harm: a gradient, and a zone.** With restitution alone (`λ=1`) an honest
  `r_exit` let the agent *declare* harm-bearing bypasses and pay for them (0
  labeled bypasses, harm 8). Harm is now priced as restitution + deterrence,
  so cheap harm is never bought, while a large enough stake can still
  justify it — proportionality, on purpose. Harm that cannot be priced
  honestly (irreversible, not compensable, or not measurable) is in the
  zone. The exit is never in the zone.
- **The gate: the zone held by the world.** Priced, the zone was for sale —
  a stake of 30 bought its way in. Now two circuits: the ledger prices acts,
  and the environment's gate stops a zone act at execution, records the
  refusal and ends the episode. No stake buys the zone; under ε-noise
  attempts still happen and are labeled, but none lands (priced: ~2 zone
  crossings per run at ε=0.5). The gate acts on what happens, never on what
  is declared, so declaring stays cheaper than trying silently. Removing
  `block` no longer brings any zone case back — it only prices the attempt.
  Honest limit: the gate sees only what the environment instruments; a zone
  step through a blind channel passes. The zone is absolute within coverage.
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
