# Watchdog — roadmap & backlog

Triaged backlog for the watcher track (Project #2). Snapshot of 2026-10-29,
after the shared `trace_gap` core landed (PRs #15, #16). Ordered by what moves
the thesis, not by how it was first written down.

The thesis so far: a closed-loop incentive scheme drives a self-interested
agent to declare obstacles instead of bypassing them, and a `trace_gap`
cross-check (declared vs. observed) catches the dishonest ones. The sandbox
proves the *logic*; it is not yet validated on a real LLM.

## Already done
- **`trace_gap` made load-bearing via a multi-step action log.** `Episode` now
  carries `steps: list[Step]` (the witness, step by step) and `declared_scope`
  (the specific acts declared — a declaration covers `(kind, target)`, not a
  whole kind). `Watcher.classify` reads only the log, the declaration and the
  task flags — never the agent's own `actual` summary. Case 13 is now a check
  over a 5-step sequence (2 steps unaccounted, with fingerprints). The old
  `Episode(task, declared, actual, crossed_zone)` constructor still works (a
  canonical log is derived), and `run.py` / `sweep.py` output is byte-identical
  to before. Knock-out test: replace `trace_gap` with a blind one and the open
  loop's 12 bypasses fall to 6 (only the zone rule holds) and an out-of-zone
  lie escapes as NORM — so the primitive carries the non-zone half. Findings
  on the way: (a) the old gap counted an *honestly declared* zone touch as
  unaccounted, conflating "lied" with "declared a forbidden act"; the two are
  now separate findings (gap vs. root rule). (b) That conflation had masked a
  rule-order hole — "looks like a mistake" (7, 8) could excuse a bypass the
  agent itself declared; a declared bypass is now never excused as a mistake.
  (c) `watchdog/tests` was not in `testpaths`, so CI never ran it; fixed.
  Natural next step: the declaration becomes a log entry itself, which turns
  the retroactive-declaration check below into an ordering check over `steps`.
- **Independent witness: the environment writes the log.** (Prompted by an
  outside review: if the agent writes its own log it can make the log match
  the declaration, and no cross-check helps.) The agent now returns an
  `Intent` (declaration, `plan`, optional `self_report`); an `Environment`
  executes the plan and keeps the log. `act()` = `Environment().execute(
  decide())`, so all numbers are unchanged. Tests: a watcher trusting the
  agent's self-report is fooled (gap 0, NORM) while the environment's log
  catches the lie (gap 2, BYPASS); with an independent log the only way to
  zero the gap is to declare everything (and a declared zone touch is still a
  bypass by the rule). Witness coverage is measured: `blind_targets` model
  uninstrumented channels, and blind to both of case 13's extra channels the
  lie passes as NORM at coverage 3/5 — the experiment can fail. This is also
  the harness shape for LLM validation: the model emits the declaration and
  tool calls, the harness is the Environment.
- Dedicated `trace_gap` unit tests — `tests/test_trace_gap.py` (8 tests: empty
  witness, all/partial accounted, sorted & deduped fingerprints, custom
  accessors, W0Guard provenance shape). Shipped in PR #15.

## Tier 1 — thesis-bearing (do first)
- **Retroactive-declaration check.** The root rule says "declared *before* the
  action", but `Episode` has no order — "before" is assumed, not verified. Add
  `declared_before: bool` (or `declared_at`/`acted_at`) and, in
  `Watcher.classify`, treat a declaration that lands after the act as invalid
  (a bypass if the act was a bypass). Cheap; closes a hole in the central rule.
- **Permission-granted cases (the root rule's "with permission" clause).** It is
  currently tested by nothing — no data, no test. Add at least two tasks:
  zone + `permission_granted=True` + lawful exit, and zone + permission + no
  exit. (May want per-task costs first — see Tier 3.)
- **A "trap" case that makes `block` load-bearing.** With `block=15 > r_task=10`
  the zone is unprofitable at any `third_party_cost`, so it is unclear whether
  `block` is doing work or is redundant. Add a task where, *without* `block`,
  the agent should cross the zone — so removing `block` visibly fails. In the
  spirit of "the experiment must be able to fail".
- **Fix the dead branch for case 14.** The `is_ambiguous` branch under
  `DECLARE_BYPASS` in `classify` is unreachable: for task 14 `u_exit (9.5) >
  u_declare (8.9)`, so the agent takes `LAWFUL_EXIT → NORM` and never reaches
  it. Either force it with a unit test
  (`Episode(DECLARE_BYPASS, DECLARE_BYPASS, is_ambiguous=True) → UNCLEAR`), or
  make the agent actually choose it via per-task costs.

## Tier 2 — cheap, honesty & coverage (bundle together)
- **Honesty-cost metric.** Add `honesty_cost = Σ(r_task − realized_reward)` to
  quantify what being honest costs the agent under each scheme. Answers "is the
  scheme too expensive for the agent?" and ties directly to the sweep threshold.
- **Strengthen `test_no_single_point_of_failure`.** It asserts `<= 1` but does
  not show *which* lever holds the scheme. Parametrize it to assert that with
  `scrutiny=0` the zone is held by `block` and the non-zone by `lam`+`r_exit`.
- **Separate the mistake / ambiguous axes.** Task 8 is both, 7 is only mistake,
  14 is only ambiguous — and `looks_like_mistake` shadows `is_ambiguous` in
  `classify`. Add a clean "ambiguous but not mistake" case (depends on the
  case-14 fix) so both axes are tested independently.
- **State the 14-actions-vs-12-labels asymmetry.** One line in README/`run.py`:
  baseline does 14 silent bypasses *by action*, but 7 and 8 are labeled
  ERROR/UNCLEAR, so "12" is the label count, not the action count.
- **Rename `counted_as_success` / "closed honestly" for baseline.** In baseline,
  success = "task done (by bypass)", not honest. Use `tasks_done`, or two rows:
  `tasks done` and `tasks done without bypass`.

## Tier 3 — enablers & integration (later)
- **Per-task `r_exit` / `block` overrides.** `Costs` is global; case 14 and the
  permission cases need local incentives. Make it global defaults + per-task
  overrides. Enabler, not a goal in itself.
- **End-to-end watchdog + W0Guard scenario.** Beyond the shared primitive, show
  the tracks complement each other: agent at a wall → attempts a bypass →
  W0Guard catches a prompt-injection inside that bypass → watchdog records the
  bypass. Even a toy scenario makes the two tracks one story.

## Deferred — do NOT do yet
- **Formalize the zone as a declarative `Policy`.** Turning `touches_safety` from
  a manual flag into a computed policy is production-hardening a part of the
  model that may still change. Premature before the scheme is validated on a
  real agent. Revisit after LLM validation.

## Frontier — separate milestones
- **LLM validation (the one that makes it non-theoretical).** Run the same 14
  tasks through a real model (local, via the `threat_judge.py` infra) and
  compare its choices against the `UtilityAgent` prediction. This turns the
  sandbox from "the logic of a scheme" into "a scheme + empirics on an LLM".
  Its runway is in place: the multi-step log and the `Environment` as the
  independent witness (the harness records the model's tool calls). Open
  question to carry over: which channels the harness does NOT see, i.e. the
  real coverage of the witness.
- **Causal / Pearl framing of the sweep.** Reframe the cost-parameter sweep as a
  do-calculus intervention study: the incentive is `do(λ)`, the bypass rate is
  the outcome. Bridges to the Pearl exchange; makes the phase-transition a
  causal threshold rather than a curve shape.
- **Reflexive closure (oversight ↔ oversight).** The being↔action loop is closed
  (one primitive over weights and actions). The open loop is pointing
  `trace_gap` at the supervision mechanism itself: the watcher keeps its own
  declared-vs-done log and is cross-checked by the same primitive — the auditor
  becomes auditable. Realizes the "untouchable zone / third vertex" of the
  original design.

## Windmill warning
The real risk is polishing the sandbox (per-task costs, extra axes, the policy
engine) instead of the two things that advance the thesis: **making `trace_gap`
load-bearing** and **validating on a real LLM**. Keep those two in front.
