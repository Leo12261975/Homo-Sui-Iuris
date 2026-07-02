# Bearer Protocol Specification (Draft)

**Status:** Draft for review — not yet implemented
**Scope:** Issue follow-up to `core_engine.py` (Issue #1) — this is Variant B:
turning the current `request_bearer_approval()` stub into a real reporting
and signature-request mechanism.
**Relation to other issues:** This spec assumes `core_engine.py` as-is. It
does not depend on Issue #2 (Erythrocytes) or #3 (Leukocytes), though it is
the natural place where a future DCT (Dynamic Correction Threshold) module
would plug in.

---

## 1. Problem Statement

In the current prototype, when `UpdateLoop` attempts to modify a protected
W0 invariant, two things happen:

1. `CriticalityMatrix.update()` raises `ImmutableWeightViolation`.
2. The exception is caught and printed to the console.

This is sufficient to *prove* the guard works, but it is not a mechanism a
real Bearer (the human operator with liability, per the manifesto) could
actually use. There is no persistent record, no structured explanation of
*why* the system wanted to override an invariant, and no real approval
step — `request_bearer_approval()` currently just prints a line and returns
`True` unconditionally, regardless of what the human would actually decide.

Variant B replaces this stub with a minimal but real reporting and
signature-request system.

## 2. Objective

Build a self-contained module, `bearer_protocol.py`, that:

- Generates a structured, human-readable **report** any time the system
  attempts an action that would touch a W0 invariant or exceeds an
  irreversibility threshold.
- Presents that report to the Bearer through a **signature request** —
  a explicit approve/deny decision point, not a side effect.
- Keeps a persistent, append-only **audit log** of every request and its
  outcome, regardless of whether it was approved, denied, or timed out.
- Does **not** silently proceed on ambiguous cases. Absence of a Bearer
  response is treated as "no," not as "yes."

## 3. Explicit Non-Goals (for this iteration)

To avoid the trap of trying to build everything at once:

- **No cryptographic signatures yet.** The manifesto mentions
  "cryptographically protected" invariants; this spec deliberately stops at
  a plain, auditable approve/deny record. Real signing (e.g. GPG, hardware
  keys) is a later, separate concern — bolting it on now would block a
  working MVP on a much harder problem.
- **No UI.** Signature requests are file- or console-based for this
  iteration. A notification channel (email, push, chat bot) is future work.
- **No automatic conflict resolution between multiple pending requests.**
  If several violations queue up, they are handled strictly in order.
- **No connection to Erythrocytes/Leukocytes (#2/#3) yet.** This module
  only reacts to violations raised by `core_engine.py`'s own W0 guard.

## 4. Data Contract

This is the part later modules (and #2/#3) may want to read, so it should
be stable and simple.

### 4.1 `BearerReport`

```python
@dataclass
class BearerReport:
    report_id: str          # UUID, generated at creation time
    timestamp: str          # ISO 8601, UTC
    trigger: str            # e.g. "W0_invariant_violation", "irreversible_action"
    invariant_name: str     # e.g. "BearerIntegrity"
    attempted_old_value: float
    attempted_new_value: float
    triggering_error: float # |E| that caused the attempted change
    risk_level: str         # "low" | "medium" | "high" — see 4.3
    explanation: str        # short, human-readable justification generated
                             # by the system (not a black-box decision)
    status: str              # "pending" | "approved" | "denied" | "expired"
```

### 4.2 `SignatureRequest`

Wraps a `BearerReport` with the approval workflow state:

```python
@dataclass
class SignatureRequest:
    report: BearerReport
    created_at: str
    resolved_at: str | None
    resolution: str | None   # "approved" | "denied" | None (still pending)
    resolver_note: str | None  # optional free-text from the Bearer
```

### 4.3 Risk Classification (initial heuristic)

| Risk level | Condition (draft — open for discussion)                        |
|------------|------------------------------------------------------------------|
| `low`      | Non-immutable weight, error just above the active threshold     |
| `medium`   | Non-immutable weight, error > 3x threshold (current shock logic)|
| `high`     | Any attempt to touch a W0 invariant directly                    |

This table is intentionally simple and almost certainly incomplete — it's a
starting point for discussion, not a settled taxonomy.

## 5. Core Components to Implement

### 5.1 `ReportGenerator`
- Input: the `ImmutableWeightViolation` (or near-miss condition) plus
  context from `CriticalityMatrix` and `UpdateLoop`.
- Output: a populated `BearerReport`.
- Responsible for producing the `explanation` field in plain language —
  this is the "structured, multi-layered justification file" the manifesto
  describes, scoped down to something buildable now.

### 5.2 `ApprovalChannel` (interface, not implementation)
- Abstract interface with one required method:
  `request_signature(report: BearerReport) -> SignatureRequest`
- **Two concrete implementations for this iteration:**
  - `ConsoleApprovalChannel` — for local development: prints the report,
    blocks on `input()` for y/n.
  - `FileApprovalChannel` — writes the report to
    `/pending_approvals/{report_id}.json`, polls for a corresponding
    `{report_id}.decision.json` written by the Bearer (or a future UI).
- Same reasoning as the `ThresholdStrategy` pattern in `core_engine.py`:
  `bearer_protocol.py` should not care which channel is used.

### 5.3 `AuditLog`
- Append-only. Every `SignatureRequest`, regardless of outcome, gets
  written — including ones that expire unresolved.
- Format: JSON Lines (`audit_log.jsonl`) — one record per line, easy to
  diff, easy to grep, no external dependencies.
- No entries are ever deleted or rewritten. If a decision needs to be
  reversed, that's a new entry, not an edit to an old one.

### 5.4 Integration Point in `core_engine.py`
- Replace the current `request_bearer_approval()` stub with a call into
  `bearer_protocol.ReportGenerator` + `ApprovalChannel`.
- `UpdateLoop._recalibrate()` must not proceed past a `high`-risk action
  until `SignatureRequest.resolution == "approved"`.

## 6. Open Questions for Tomorrow's Session

These need a decision before implementation starts — flagging them now so
we don't discover them mid-build:

1. **Timeout behavior.** If a signature request sits unresolved, does it
   expire after N minutes/hours and default to "denied," or does it block
   indefinitely? (Recommendation: expire and deny — an unattended system
   should fail closed, not open.)
2. **Where does `low`-risk sit?** Should low-risk events even generate a
   signature request, or just an audit log entry with no approval step?
   Requiring sign-off on everything risks alert fatigue, which defeats the
   purpose.
3. **File-based vs. something else for `FileApprovalChannel`.** JSON files
   are simple and dependency-free, but polling is inelegant. Acceptable for
   MVP, but worth flagging as a known limitation in the README.
4. **Does `resolver_note` matter for anything besides the audit trail?**
   E.g., should a denial with a note feed back into `CriticalityMatrix` as
   a signal, or is it purely for human record-keeping at this stage?

## 7. Suggested File Structure

```
/bearer_protocol
    __init__.py
    bearer_protocol.py      # BearerReport, SignatureRequest, ReportGenerator
    approval_channels.py    # ApprovalChannel interface + Console/File impls
    audit_log.py            # AuditLog
    /pending_approvals      # runtime-generated, gitignored
    audit_log.jsonl         # runtime-generated, gitignored (or committed
                             # as an example with synthetic data — TBD)
```

## 8. Definition of Done (for the MVP)

- [ ] Running `core_engine.py` with a forced high-risk violation produces a
      `BearerReport` with all fields populated meaningfully (no empty
      strings, no placeholder values).
- [ ] `ConsoleApprovalChannel` blocks execution and visibly waits for y/n.
- [ ] A denial actually prevents the attempted change — `UpdateLoop` must
      not proceed as if approval had been granted.
- [ ] Every request (approved, denied, or expired) is present in
      `audit_log.jsonl` after the run.
- [ ] README/docstring makes clear this is still a **local, single-machine
      simulation** of the Bearer relationship — not a claim of a production
      security system.

---

*As with Issue #1: this spec formalizes a mechanism, not a guarantee. The
goal is a working, auditable approval loop that a skeptical engineer can
read end-to-end in a few minutes — not a claim that this constitutes real
legal or cryptographic accountability.*
