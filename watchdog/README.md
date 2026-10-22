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

## What's inside

| file | what it is |
|------|------------|
| `MODEL.md`   | the sandbox model in words — entities, the two schemes, what we count |
| `watcher.py` | entities, two agents (baseline / loop), the watcher |
| `tasks.py`   | 14 tasks modeled on the cases from the labeling — this is data, edit freely |
| `run.py`     | the experiment run and bypass count |
| `tests/`     | tests, including the control that the experiment is able to fail |

## Running

    python3 run.py                  # run and compare the two schemes
    python3 tests/test_watcher.py   # tests (or: python3 -m pytest tests/ -q)

## Result

| | without the scheme | with the scheme |
|---|---|---|
| bypasses (watcher's label) | 12 | 0 |
| of which touched the safety zone | 8 | 0 |
| tasks closed honestly | 12/14 | 12/14 |

The closed loop removes bypasses without losing closed tasks. But the
numbers do not prove themselves — two controls do that:

- **Stimulus control.** The same loop agent has "exit = success" taken
  away — and it returns to bypasses. So the difference is created by the
  incentive scheme, not by the watcher renaming a bypass into a norm. The
  experiment is able to fail, and in the control it fails where it should.
- **Honesty control.** A dishonest agent (declared one thing, did another)
  is caught by the declared-vs-log cross-check as a bypass.

## Honest limitations

- The agents are deterministic automata, not LLMs. The sandbox measures the
  logic of the incentive scheme, not how a real model behaves at a wall.
- The costs (`third_party_cost`, "a block costs more than the exit") are set
  by hand. The next step is to tie them to real magnitudes, or to sweep a
  grid of values and find the cost ratio at which the scheme stops working.

## Relation to W0Guard

This is a sibling track, not part of the engine. The shared core is the
trace-gap heuristic (cross-checking the declared against the observed). Over
time it is worth factoring out as a common principle used by both, rather
than merging the two mechanisms into one.
