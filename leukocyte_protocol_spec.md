# Digital Leukocyte Protocol Specification — Issue #3

**Status:** Implemented (MVP) — `leukocyte_protocol.py`, tested end-to-end via
`run_network_demo()`.
**Scope:** Builds entirely on top of `core_engine.py` and `erythrocyte.py`
as they exist today. **No changes were made to either file.** Integration
happens through two seams that were already designed to be extensible:
the `ApprovalChannel` interface, and a new pre-filter step in front of any
externally-originated weight write.
**Source note:** This spec is written after implementation, not before —
unlike `bearer_protocol_spec.md` and `erythrocyte_spec.md`, which were
design documents that preceded their code. This document records what was
actually built and why, so it can be reviewed and revised like the others.

---

## 1. Problem Statement

Issue #2 (Erythrocyte) detects weight poisoning *after* it has already
happened inside a single node — it reads history that already exists in
`CriticalityMatrix`. That is necessarily reactive and local: a node has to
be poisoned once, notice it, and correct it before it has any defense at
all.

Issue #3 asks for two additional properties that a single node cannot
provide by itself:

1. **A pre-filter ("far approaches" defense):** a way to refuse a known
   attack pattern before it ever touches `CriticalityMatrix`, rather than
   detecting it after the fact via Erythrocyte's history-based analysis.
2. **Network immunity:** once *any* node in the network has detected and
   corrected an attack, other nodes should not have to pay the same cost
   of first exposure — they should recognize the same pattern immediately.

## 2. Non-Invasive Integration — Why No Changes to Existing Files

`core_engine.py` already contains two abstract interfaces designed
specifically so new behavior can be added without touching the classes
that use them: `ThresholdStrategy` (Issue #1) and `ApprovalChannel`
(Variant B). `UpdateLoop` only knows it's talking to *an* `ApprovalChannel`
— never which concrete implementation.

`LeukocyteApprovalChannel` uses exactly that seam: it wraps any inner
`ApprovalChannel`, delegates the actual approve/deny decision to it
unchanged, and only *observes* the outcome. When it sees an approved
`erythrocyte_oscillating_distortion` report pass through, it notifies the
owning `LeukocyteAgent`. Neither `UpdateLoop` nor `erythrocyte.py` needed
any modification, and neither is aware this layer exists.

The second integration point — the Guard layer — has no existing seam to
attach to, because it operates *before* anything reaches
`CriticalityMatrix`, not after. It is implemented as a standalone
pre-filter function (`guarded_direct_write`) that any external-write path
is expected to call before invoking `CriticalityMatrix.update()` directly.
This is a convention, not an enforced boundary — see Section 6.

## 3. Data Contract

### 3.1 `AntigenSignature`

```python
@dataclass
class AntigenSignature:
    signature_hash: str      # deterministic fingerprint, see 3.2
    target_weight: str
    distortion_type: str     # "static" | "oscillating"
    origin_node: str
    timestamp: str
    context_label: str       # stand-in for the actual attack content
```

### 3.2 Signature hash — explicitly not cryptographic attack fingerprinting

```
signature_hash = sha256(target_weight | distortion_type | context_label)[:16]
```

This is a **conditional/simulated** fingerprint, not a hash of real
malicious prompt or payload content — this simulation has no such content
to hash. Two attacks are "the same" here if and only if they share the
same `target_weight`, `distortion_type`, and `context_label` string. A
real implementation would need genuine content-based fingerprinting
(e.g. hashing the actual sequence of injected values, or a learned
embedding of attack shape) to recognize variations of the same attack —
this MVP only recognizes exact replays. Flagged as a non-goal below
(Section 6), not silently glossed over.

### 3.3 `AntigenBlacklist`

Flat `dict[signature_hash -> AntigenSignature]` per node. Same
"no premature graph structure" principle already used for
`CriticalityMatrix` and for Erythrocyte's design — a network topology
model was deliberately not introduced for a 3-node demo.

## 4. Components Implemented

- **`LeukocyteApprovalChannel`** — non-invasive wrapper around any
  `ApprovalChannel`; triggers antigen generation on approved oscillation
  escalations.
- **`LeukocyteAgent`** — one per node. Owns the local `AntigenBlacklist`,
  exposes `guard()` (pre-filter) and `on_approved_oscillation()` /
  `broadcast_antigen()` / `receive_antigen()` (network propagation).
- **`P2PNetworkSimulation`** — owns a set of independently-constructed
  nodes (`NodeContext`: its own `CriticalityMatrix`, `Model`, `UpdateLoop`,
  `LeukocyteAgent`) and a single method, `deliver_antigen()`, which is the
  only thing actually shared across nodes.
- **`SecurityEventLog`** — append-only JSONL, same philosophy as
  `AuditLog`, kept as a separate file/schema rather than reusing
  `AuditLog`'s `SignatureRequest` format, since gate-level blocks are a
  different kind of event (no Bearer decision involved at all — the point
  is that the Bearer is never even asked).

## 5. Verified Behavior (`run_network_demo()`)

Three phases, run and confirmed against actual output (not just designed
on paper):

1. **Node_A, first exposure:** attack pattern applied 7 times, blocked
   once — the single self-block is a side effect of Node_A generating its
   own antigen mid-attack and immediately recognizing its own subsequent
   injection attempt. Not a bug: a node is also immune to itself once it
   has generated a signature.
2. **Node_B, exact replay of Node_A's attack:** 0 applied, 8 blocked — the
   attack never reached `CriticalityMatrix` a single time.
   `adaptability` on Node_B only changed due to its own legitimate
   `UpdateLoop` activity, never due to the attack.
3. **Node_C, control — a different, unseen attack pattern:** 7 applied, 1
   blocked (same self-block pattern as Node_A) — proving Node_A's earlier
   broadcast did **not** cause Node_C to block an unrelated attack. The
   guard is signature-specific, not a blanket refusal of direct writes.

This distinguishes real signature-matching from a trivial "block
everything" implementation, which would have passed Phase 2 but failed
Phase 3.

## 6. Explicit Non-Goals for This MVP

Per this project's established practice (see `bearer_protocol_spec.md`
Section 3, `erythrocyte_spec.md` Section 4): naming what was deliberately
left out is part of the spec, not an afterthought.

- **Unbounded blacklist growth — no TTL, no eviction, no capacity limit.**
  `AntigenBlacklist` accumulates every signature it ever sees, forever.
  For a 3-node demo this is irrelevant; for a real long-running P2P
  network it is not — an unbounded blacklist is both a memory-growth
  problem and a potential attack surface of its own (flooding a node with
  junk signatures to exhaust memory). Explicitly deferred: no expiry
  policy, no LRU eviction, no size cap in this iteration.
- **No real cryptographic attack fingerprinting**, as covered in Section
  3.2 — only exact-match replay detection via a simple deterministic hash
  of three fields.
- **No enforcement that external writers actually call the guard.**
  `guarded_direct_write()` is a convention for this codebase's own attack
  simulation, not a boundary enforced by `CriticalityMatrix` itself.
  Anything with a direct reference to a `CriticalityMatrix` can still call
  `.update()` directly and skip the guard entirely. A real deployment
  would need the guard to be the *only* path to the matrix from outside
  `UpdateLoop`, not an opt-in convention.
- **No network trust/authentication model.** `deliver_antigen()` delivers
  to every other node unconditionally. There is no mechanism here to
  prevent a compromised node from broadcasting false antigens to trigger
  denial-of-service against legitimate weight values (poisoning the
  immune system itself). Worth flagging for a future issue, not solved
  here.
- **No partial/fuzzy signature matching.** A near-identical attack with a
  slightly different `context_label` (or a real attack with genuinely
  different content but the same underlying pattern) produces a different
  hash and is not recognized. Only exact replays are caught.
- **No persistence across process restarts.** `AntigenBlacklist` is
  in-memory only; restarting a node forgets everything it has learned,
  including from its own past detections.

None of these are oversights — each was a reachable next step that was
deliberately not taken, to keep this MVP proportional to a 3-node demo
rather than a production distributed system.

## 7. Open Questions for a Future Iteration

1. If a TTL/eviction policy is added later, what should it be keyed on —
   age, hit frequency, or a fixed capacity with LRU eviction? No default
   is proposed here; this is intentionally left for the issue that
   actually tackles Section 6's first non-goal.
2. Should `guard()` become the enforced-only path into
   `CriticalityMatrix.update()` (i.e. should direct calls be disallowed
   for non-`UpdateLoop` callers at the type level), or does that overreach
   into a stricter access-control model than this project wants?
3. Antigen trust: should a received antigen require any corroboration
   before being blacklisted (e.g. only trusted after N independent nodes
   report the same signature), or is single-source trust acceptable for
   now? Directly related to the "no trust model" non-goal above.

## 8. Definition of Done (retrospective — all met by current implementation)

- [x] `AntigenSignature`, `LeukocyteAgent`, `P2PNetworkSimulation`
      implemented without modifying `core_engine.py` or `erythrocyte.py`.
- [x] Guard layer blocks a known-signature write before it reaches
      `CriticalityMatrix.update()` — verified via Node_B's 0-applied result.
- [x] Antigen broadcast on approved oscillation correction — verified via
      Node_A generating and propagating a signature mid-attack.
- [x] Control case proves signature-specificity, not blanket blocking —
      verified via Node_C.
- [x] Non-goals from Section 6 documented rather than silently left
      unimplemented.

---

*As with the other specs in this repository: this documents a working
simulation of a network immune pattern, not a production security
guarantee. Its stated non-goals are as much a part of the spec as what it
does implement — reviewers should treat gaps in Section 6 as known and
intentional, not as bugs to report.*
