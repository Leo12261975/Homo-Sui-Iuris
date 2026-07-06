# Sovereign Action Protocol Specification — Issue #6

**Status:** Implemented (MVP) — `sovereign_action_protocol.py`, tested
end-to-end via `run_sovereignty_demo()`. Merged.
**Scope:** Builds directly on `core_engine.py` (`CriticalityMatrix`,
`ApprovalChannel`, `ReportGenerator`) and `leukocyte_protocol.py`
(`SecurityEventLog`). No changes were made to either file.
**Source note:** Written after implementation, same practice as
`leukocyte_protocol_spec.md` — this records what was actually built and
why, for review, not a design document that preceded the code.

---

## 1. Problem Statement

Issues #1–#3 protect a single node's internal state (weights, knowledge)
against corruption from inside or from the network. None of them govern
what happens when a node's AI acts *outward* — proposing or accepting a
binding agreement with another node on the Bearer's behalf.

Issue #6 asks for exactly that: a way for two personal AIs to negotiate
and activate a `CognitiveContract` autonomously, while guaranteeing that
no contract, however it's framed or whatever it's traded for, can result
in a node signing away control of its own protected core. The risk isn't
a malformed contract — it's a *well-formed, attractively-framed* one that
happens to cede sovereignty, which is the predatory-contract test case
this spec exists to catch.

## 2. Continuity With the Existing Core — What Was Reused, and Why

- **`CriticalityMatrix` (core_engine.py), not a new invariant list.**
  `SovereignActionEngine._check_sovereignty_violation()` reads
  `Weight.is_immutable` directly off the receiving node's own matrix — the
  same object Issues #1–#3 already use. This means the set of "things a
  contract can never cede" is defined in exactly one place in the whole
  repository. If a new W0 invariant is added to `CriticalityMatrix` in the
  future, this module protects it automatically, with no code change here.
- **`ApprovalChannel` / `ReportGenerator` (core_engine.py), reused, not
  duplicated.** Benign contracts that clear the sovereignty check can
  optionally be routed through the same Bearer-approval infrastructure
  Variant B built — a second, human-facing check layered on top of the
  structural one, using the existing `BearerReport` format rather than a
  parallel one.
- **`SecurityEventLog` (leukocyte_protocol.py), reused, not duplicated.**
  Contract rejections are logged with the same append-only JSONL pattern
  already used for gate-level security events (antigen blocks, knowledge
  quarantine). One log format, one place to look, across three different
  attack surfaces.

## 3. Data Contract

### 3.1 `CognitiveContract`

```python
@dataclass
class CognitiveContract:
    contract_id: str
    topic: str
    terms: Dict[str, Any]
    party_a_node: str
    party_b_node: str
    signature_party_a: str = ""
    signature_party_b: str = ""
    status: str = "draft"    # "draft" | "pending" | "active" | "rejected"
    rejection_reason: Optional[str] = None
    timestamp: str
```

### 3.2 `terms` — structured fields, not free text

Only two keys are actually read by the sovereignty check:

| Key                 | Type            | Meaning                                                        |
|----------------------|-----------------|------------------------------------------------------------------|
| `cedes_control_of`   | `Optional[str]` | Name of a weight/invariant this contract proposes handing control of. `None` if the contract makes no such claim. |
| `third_party`        | `Optional[str]` | Who control would be ceded to — used only for the rejection message, not for the decision itself. |

Everything else in `terms` (`description`, `data_volume_mb_per_day`,
`reciprocal`, etc.) is free-form and carried through to both signatures
for record-keeping, but **not evaluated** by this engine. See Section 6.

### 3.3 Signatures — explicitly emulated

```
sign_contract(contract_id, topic, terms, signer_node)
    = sha256(contract_id | topic | json(terms, sorted) | signer_node)
```

Same honesty already applied to `leukocyte_protocol.AntigenSignature` and
`mitochondrion_protocol.DataPayload`: this is a deterministic stand-in for
"signed with the Bearer's private key," not a real signing scheme. No key
material exists anywhere in this simulation.

## 4. Components Implemented

- **`SovereignActionEngine`** — one per node. `initiate_contract()` builds
  and self-signs a proposal. `evaluate_and_sign_contract()` is the
  receiving side's single entry point — every contract passes through it
  before any second signature is possible.
- **Check ordering inside `evaluate_and_sign_contract()`, in this exact
  sequence:**
  1. `_check_sovereignty_violation()` — structural, unconditional, no
     approval channel can override it. A contract that fails here is
     rejected before the Bearer is ever consulted.
  2. `ApprovalChannel.request_signature()` (only if configured) — a
     second, human-facing check for contracts that already passed step 1.
  3. Second signature + `status = "active"`.

  This ordering is itself a design decision worth naming explicitly: it
  means "the Bearer approved it" is never sufficient to override a W0
  violation, and it also means the Bearer is never even bothered with a
  contract that was going to be refused structurally anyway.

## 5. Verified Behavior (`run_sovereignty_demo()`)

Two phases, run and confirmed against actual output:

1. **Fair contract** (`cedes_control_of: None`) — both signatures present,
   `status == "active"`.
2. **Predatory contract** (`cedes_control_of: "BearerIntegrity"`) —
   rejected at step 1, `signature_party_b` never populated, rejection
   logged to `SecurityEventLog` with a fingerprint of the terms (not the
   raw terms themselves, consistent with not persisting full payloads
   unnecessarily in a security log).

Both phases used `AutoApprovalChannel(always_approve=True)` for the demo,
per this project's established pattern of unattended, reproducible demo
runs (see `bearer_protocol_spec.md`, `core_engine.py` Part 1). The
predatory case never reaches the approval channel at all regardless of its
configured behavior — that's the point being demonstrated.

## 6. Explicit Non-Goals for This MVP

Per this project's established practice: naming what's deliberately left
out is part of the spec.

- **No real natural-language understanding of `terms['description']`.**
  The sovereignty check is a structured-field lookup
  (`terms.get('cedes_control_of')`), not a semantic reading of the
  contract's prose. A contract that describes ceding core control only in
  free text, without setting the structured field, is **not caught** by
  this MVP. This is not a hidden gap — the demo's predatory contract
  deliberately sets both the structured field AND a matching description,
  precisely because only the structured field is actually checked. A real
  implementation would need genuine NLU or mandatory structured-term
  schemas enforced at the point of contract creation, not just at
  evaluation.
- **No identity verification of `party_a_node` / `party_b_node`.** Node
  identity is a plain string. Nothing in this module verifies that a
  message claiming to be from `Node_Human_A` actually originated there —
  spoofing a counterparty's identity is out of scope here, same category
  of gap already flagged for `AntigenSignature.origin_node` in
  `leukocyte_protocol_spec.md`.
- **No negotiation or counter-proposal flow.** A contract is accepted or
  rejected exactly as sent; there is no mechanism for the receiving node
  to propose amended terms. Every rejected contract is a dead end, not a
  starting point for renegotiation.
- **No contract lifecycle beyond activation.** There is no expiry,
  amendment, revocation, or dispute-resolution mechanism once a contract
  reaches `"active"`. Once signed, this MVP has nothing more to say about
  it.
- **`third_party` is not itself validated.** A predatory contract's
  `third_party` field is free text used only for the human-readable
  rejection message — there is no registry of known-bad or known-good
  third parties it's checked against.
- **Ceding control of a non-immutable weight is currently treated as
  automatically acceptable.** `_check_sovereignty_violation()` returns
  `None` (no violation) for any `cedes_control_of` target that exists in
  the matrix but isn't marked `is_immutable`. This is a deliberate
  MVP choice — such a term is treated as a legitimate negotiated
  arrangement — but it means a contract ceding control of, say,
  `adaptability` for the duration of an agreement is signed with no
  additional scrutiny beyond whatever the (optional) Bearer approval step
  provides. Whether that deserves its own risk tier is an open question
  (Section 7).

## 7. Open Questions for a Future Iteration

1. Should ceding control of a *mutable but non-trivial* weight (as
   opposed to `None`, i.e. no claim at all) always be routed through the
   `ApprovalChannel`, even in configurations where benign contracts
   normally skip it? Right now that decision is entirely up to whether
   the engine was constructed with an `approval_channel` at all — there's
   no way to require Bearer review specifically for contracts that touch
   *any* named weight while still auto-signing pure data-exchange terms.
2. Is a single `cedes_control_of: Optional[str]` field expressive enough,
   or should contracts be able to name multiple invariants/weights at
   once? The current schema can't represent "this contract touches both
   `adaptability` and something else" without inventing a second key.
3. How should this module's structured-field check relate to a future
   NLU-based check on `description`, if one is ever added — should they
   be independent gates (either one can reject), or should NLU only ever
   be advisory, with the structured field remaining the sole authoritative
   signal? Worth deciding before any NLU work starts, not after.

## 8. Definition of Done (retrospective — all met by current implementation)

- [x] `CognitiveContract` and `SovereignActionEngine` implemented without
      modifying `core_engine.py` or `leukocyte_protocol.py`.
- [x] Sovereignty check reads `is_immutable` directly from a real
      `CriticalityMatrix` instance, not a duplicated invariant list.
- [x] Sovereignty check runs and can reject BEFORE the `ApprovalChannel`
      is consulted — verified via the predatory-contract phase never
      populating `signature_party_b`.
- [x] Fair contract reaches `status == "active"` with both signatures
      present — verified via the fair-contract phase.
- [x] Rejections logged via `SecurityEventLog`, consistent with the
      logging pattern already established for Issue #3/#5.
- [x] Non-goals from Section 6 documented rather than silently left
      unimplemented, including the specific limitation that free-text
      sovereignty-ceding language is not detected.

---

*As with the other specs in this repository: this documents a working
simulation of a governance pattern, not a production legal or
cryptographic system. Its stated non-goals — especially Section 6's note
on free-text terms — are as much a part of the spec as what it does
implement. A reviewer who finds a contract that "should" have been
rejected but wasn't should check Section 6 before filing it as a bug: if
the violation was only expressed in prose and never in the structured
`cedes_control_of` field, that gap is documented, not accidental.*
