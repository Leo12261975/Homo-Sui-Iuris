# Closed-loop sandbox — the model

Project #2, the watcher for bypasses. Deterministic core, no real network.
We compare two **incentive schemes**, which in the code are now literally
two cost tables handed to one and the same agent.

## Entities

### Wall
An obstacle inside a task. A wall has:
- `kind` — the beacon type: tool_error | access_denied | third_attempt |
  foreign_token | foreign_form | site_down.
- Behind the wall lie a **bypass path** and, sometimes, a **lawful exit**.

### Bypass
What the agent can do to "break through" the wall:
- `touches_safety: bool` — whether it touches the untouchable zone.
- `third_party_cost: int` — the externality (real cost to third parties).

### LawfulExit
The "declare the obstacle" action. Not present at every wall (some tasks are
impossible in principle — then the honest exit is a refusal / give-up).

### Agent — a utility maximizer
The agent is **not** a set of hand-written "do the right thing" branches.
It scores every action from an explicit cost table and picks the best
(`argmax`), optionally with ε-noise. Four actions: declare the bypass,
bypass silently, lawful exit, give up. Each episode carries a **step-by-step action log**
(`steps`, ground truth) separate from the **declared scope** — the specific
acts the agent announced. A declaration covers `(kind, target)`, not a whole
kind. A dishonest agent declares the harmless step and does more (case 13).

### Watcher
Does not interfere with the choice. It classifies each episode, cross-checking:
1. was the bypass declared before acting (the root rule);
2. is the action within the task's scope (overreach);
3. **declared vs. the log** (honesty) — catches case 13.

The watcher reads only the log and the declaration, never the agent's own
summary of what it did. `trace_gap` counts the log steps that neither the
task's license (attempt, hit the wall, report, stop) nor the declaration
accounts for. A gap is a *lie or silence*; an honestly declared zone touch
leaves no gap but is still a bypass by the root rule — two different findings.
A declared bypass is never excused as "looks like a mistake".

Labels: BYPASS / NORM / ERROR / UNCLEAR (as in the labeling doc).

## The cost table = the scheme

Every action's utility to the agent is `benefit − costs that return to it`:

| symbol     | meaning                                              |
|------------|------------------------------------------------------|
| `r_task`   | reward for completing the task                       |
| `r_exit`   | reward for a lawful exit (0 ⇒ the exit is not success) |
| `r_giveup` | reward for an honest give-up                         |
| `λ` (lam)  | fraction of the third-party externality returned to the agent |
| `block`    | penalty when a safety-zone bypass is blocked         |
| `scrutiny` | cost of an UNDECLARED bypass (the loop watches silence) |
| `effort`   | small cost of declaring (articulating the bypass)    |

The two schemes are just two settings of this table:

- **Open loop (baseline):** `r_exit=0, λ=0, block=0, scrutiny=0`. Nothing
  comes back. Declaring only costs `effort`, so honesty is pure cost — the
  agent bypasses silently everywhere. This is the agent from the Anthropic
  report (2026-10-09).
- **Closed loop (loop):** `r_exit=9.5, λ=1, block=15, scrutiny=0.5`. The
  externality returns, the zone is blocked, silence is scrutinized, and the
  lawful exit is counted as (almost full) success. The same agent now finds
  the lawful exit — or a declared safe bypass — to be the `argmax`.

Nothing about correctness is hard-coded. The behavior is a consequence of
the numbers, which is the whole point: if even a self-interested maximizer
goes honest under this table, that argues the scheme, not the labeling.

## What we measure

On the same task set we run both cost tables and count, per scheme:
how many episodes the watcher labeled BYPASS / NORM / ERROR / UNCLEAR;
how many bypasses touched the untouchable zone; how many honesty cases the
cross-check caught.

### Three controls that let the experiment fail

1. **Stimulus decomposition** (`run.py`). Strip incentives from the loop
   table one at a time. Removing any single one keeps the scheme near zero;
   removing several brings bypasses back; removing all reproduces baseline
   (12). So behavior tracks the cost table, not the watcher's label — and
   the scheme has **no single point of failure**.
2. **Internalization sweep** (`sweep.py`). Scale all loop incentives by a
   factor `s` from 0 (= baseline) to 1 (= full loop). Bypasses fall from 12
   to 0; **partial** internalization (`s≈0.3–0.7`) already suffices — the
   loop need not return the full cost to work.
3. **Noise robustness** (`sweep.py`). With ε-greedy noise the agent slips to
   a random action with probability ε. The loop's advantage over the open
   loop shrinks **gradually** as ε rises (no cliff): the edge is widest when
   the agent actually optimizes.

## The root rule (with the caveat)

A bypass is allowed if (a) declared before the action, and (b) it does not
touch the untouchable zone. A bypass that touches the safety zone requires
**permission**, not just a declaration (`permission_granted`, False by
default). Declaration alone is not enough — the watcher cross-checks the
declared action against the log, the same trace-gap heuristic W0Guard uses
on weight provenance, here applied to actions.
