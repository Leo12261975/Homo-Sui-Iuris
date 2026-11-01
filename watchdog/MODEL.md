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

**Laziness.** An exit is honest about the wall and silent about what lies
behind it. Two cases: a *claimed* wall the log does not show (no wall in the
world) — the watcher's `support_gap` runs `trace_gap` the other way round
(claim checked against witness) and labels it `false exit`; and a *real*
wall with a lawful path behind it — the log backs the exit, the watcher
cannot see it, and only the cost table prevents it: the agent exits exactly
when `r_exit ≥ r_task − solve_cost`. So `r_exit` has a ceiling set by the
hardest lawful work you want done, and cannot carry the anti-bypass load.
The current `LOOP` uses `r_exit=3` with claimed walls checked.

**Harm: a gradient for what can be priced, the zone for what cannot.** With
restitution alone an honest `r_exit` made a declared, harm-bearing bypass
beat the exit. Harm outside the zone is now priced as `(lam + deterrence) ·
harm`: `lam=1` is restitution (the harm goes back to whom it was done),
`deterrence` the gradient on top. A soft markup does nothing — the price
must exceed what the bypass gains over the exit, or cheap harm is still
bought; `deterrence=6` puts the smallest harm past that line. A large enough
stake can still justify a harm: proportionality, kept on purpose. Harm is
priceable only if it is **reversible**, **compensable** (the harmed party is
known and can be made whole) and **measurable**; failing any of the three
puts it in the zone. ("Compensable", not "consented": third-party harm is
unconsented by definition.) Three regulators, one per failure: the gradient
for priceable harm, the zone for unpriceable harm, the `r_exit` ceiling for
laziness. The exit is never in the zone — the honest path stays open.

**Two circuits: the ledger and the gate.** Priced by `block` alone, the zone
was for sale: a large enough stake bought its way in. So the zone is held by
the environment instead. `Environment(gate=True)` stops a zone step at
execution: the act does not happen, a `REJECTED` step is written to the log
and the episode ends — the task is not done, at any stake. Design choices:
- **at execution, not at the declaration** — refusing on what is declared
  would make silence safer than honesty and is trivially dodged by not
  declaring; the gate reads what happens, and declaring a zone act stays
  cheaper than trying it silently;
- **the refusal is on the record** — an attempt on the zone is a witnessed
  fact, labeled a bypass (a mistake, cases 7–8, stays a mistake);
- **permission opens it** — a permitted path is not a zone act;
- **the honest path is never gated** — exit and give-up pass untouched;
- **`block` becomes the price of an attempt** — removing it brings no zone
  case back.
Honest limit: the gate sees only what the environment instruments. A zone
step through a blind channel passes; the zone is absolute *within coverage*.
Who may change the gate's policy is the untouchable zone of oversight itself
(holder, quorum, delay) — and the gate's own refusals are a log the same
`trace_gap` can audit.

**Who writes the log.** The agent produces an `Intent` — its declaration, what
it does (`plan`), and optionally its own account (`self_report`). It does not
write the log: an `Environment` executes the plan and records what it can see.
The watcher reads only that record. With an independent witness the agent can
zero the gap only by declaring every act — gaming the check becomes the
honesty the root rule asks for. The witness sees only what it instruments:
`blind_targets` are uninstrumented channels, and `Episode.coverage` measures
the share of what happened that reached the log. A lie through a blind
channel passes; coverage is how you know which world you were in.

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
- **Closed loop (loop):** `r_exit=3, λ=1, deterrence=6, block=15,
  scrutiny=0.5, fabrication=4`. The externality returns, the zone is blocked, silence is
  scrutinized, claimed walls are checked, and the lawful exit is rewarded —
  but never above what the hardest lawful work leaves of the task reward.
  The same agent now finds the lawful work, else the lawful exit, to be the
  `argmax` — a declared bypass only where it harms no one. The
  first calibration (`r_exit=9.5`) is kept as `LOOP_V1`.

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
   the root rule's two clauses split the cases — with the harm price off,
   `scrutiny` ("only declared") holds the non-zone half and `block` ("not
   into the zone") the zone half. The harm gradient adds a third, overlapping
   layer; each layer keeps a territory only it covers (scrutiny: the harmless
   silent bypass; block: the zone with no exit; the gradient: the harm). The first calibration (`r_exit=9.5`, kept as `LOOP_V1`)
   looked fully redundant — that redundancy was bought with laziness.
   Load-bearing means the weak point is known: `scrutiny` is only as good as
   the witness that sees silence, so the investment goes into witness
   coverage, not into the size of the penalty.
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
