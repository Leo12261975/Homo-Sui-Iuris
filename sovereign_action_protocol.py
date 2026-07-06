"""
Homo Sui Iuris / Free Cognitive Protocol
Issue #6 — Sovereign Action Protocol: autonomous P2P contracts under
Bearer authority.

STATUS: Simulation of an autonomous contracting pattern (propose -> sign ->
counter-evaluate -> counter-sign -> activate), gated by the same W0
invariants already enforced inside core_engine.py. Not a real legal
contracting system and not real cryptographic signing — `_sign()` is an
emulated private-key signature (a salted hash), consistent with how this
project has already been honest about simulated crypto in
leukocyte_protocol.py (`signature_hash`) and mitochondrion_protocol.py
(`cryptographic_signature`). The point of this module is the *gate*, not
the cryptography.

Continuity with the existing core:

  - Each node's SovereignActionEngine holds a real core_engine.py
    CriticalityMatrix (the same class Issue #1-#3 use), constructed with
    the same W0 invariants (BearerIntegrity, TruthPriority,
    CorrigibilityChannel). Sovereignty checking is not a re-implementation
    of "what counts as protected" — it reads `Weight.is_immutable`
    directly off that matrix. If a contract proposes ceding control of
    anything the matrix itself marks immutable, it is refused
    unconditionally, exactly like core_engine.py's own
    ImmutableWeightViolation guard refuses direct attempts to touch W0.
  - Benign contracts can optionally be routed through a real
    core_engine.py ApprovalChannel (reusing ReportGenerator/BearerReport)
    before final signature — reusing Variant B's infrastructure rather
    than inventing a parallel approval mechanism.
  - Rejections are logged via leukocyte_protocol.py's SecurityEventLog —
    the same append-only JSONL pattern already used for gate-level
    security events elsewhere in this repo.

Known non-goals for this MVP:
  - No real NLU/legal review of free-text `terms`. Sovereignty violation
    detection is a structured-field check (`cedes_control_of`), not
    language understanding of a `description` string. A contract that
    describes a sovereignty-ceding arrangement only in prose, without
    setting the structured field, will NOT be caught by this MVP — see
    `_check_sovereignty_violation` for exactly what is and isn't checked.
  - No real identity verification of `party_a_node` / `party_b_node` —
    node identity is just a string, not tied to any authentication.
  - No negotiation/counter-proposal flow — a contract is accepted or
    rejected as-is, never amended.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from core_engine import (
    ApprovalChannel,
    BearerReport,
    CriticalityMatrix,
    ReportGenerator,
)
from leukocyte_protocol import SecurityEventLog


# ---------------------------------------------------------------------------
# CorrigibilityChannel — the live enforcement mechanism (Step 2)
# ---------------------------------------------------------------------------

class CorrigibilityInvariantMissing(Exception):
    """
    Raised when a SovereignActionEngine's own CriticalityMatrix does not
    register 'CorrigibilityChannel' as an immutable W0 invariant. An
    engine refuses to process any contract at all in this state — see
    SovereignActionEngine._verify_corrigibility_invariant.
    """


class CorrigibilityChannel:
    """
    The live, stateful correction channel a human Bearer uses to interrupt
    or veto contract processing.

    This is deliberately distinct from the frozen W0 weight of the same
    name inside CriticalityMatrix. That weight only *declares* the
    invariant exists (value=1.0, is_immutable=True) — nothing in
    core_engine.py ever reads its value to gate an action, which is
    exactly the gap flagged earlier ("registered but never enforced").
    This class is the actual mechanism; the W0 weight is the separate
    promise, checked structurally at engine construction time (see
    SovereignActionEngine._verify_corrigibility_invariant), that the
    mechanism can't be quietly removed from a node's matrix.

    Two signal levels:
      - veto: hard stop. Refuses ALL contract processing unconditionally,
        the moment it is checked — before sovereignty evaluation and
        before any ApprovalChannel is consulted. Independent of the
        contract's own terms and of every other weight in the matrix.
      - manual_review_required: soft stop. Contracts that would otherwise
        auto-sign (no ApprovalChannel configured, or one that would
        auto-approve) are instead forced through explicit Bearer review;
        a node with no ApprovalChannel at all fails closed rather than
        auto-signing while this flag is set.
    """

    def __init__(self) -> None:
        self._veto_active = False
        self._veto_reason: Optional[str] = None
        self._manual_review_required = False
        self._manual_review_reason: Optional[str] = None

    # --- veto: hard stop ---------------------------------------------------

    def raise_veto(self, reason: str) -> None:
        self._veto_active = True
        self._veto_reason = reason

    def clear_veto(self) -> None:
        self._veto_active = False
        self._veto_reason = None

    def is_veto_active(self) -> bool:
        return self._veto_active

    @property
    def veto_reason(self) -> Optional[str]:
        return self._veto_reason

    # --- manual review: soft stop ------------------------------------------

    def require_manual_review(self, reason: str) -> None:
        self._manual_review_required = True
        self._manual_review_reason = reason

    def clear_manual_review(self) -> None:
        self._manual_review_required = False
        self._manual_review_reason = None

    def is_manual_review_required(self) -> bool:
        return self._manual_review_required

    @property
    def manual_review_reason(self) -> Optional[str]:
        return self._manual_review_reason


# ---------------------------------------------------------------------------
# Signature helper — explicitly emulated, see module docstring
# ---------------------------------------------------------------------------

def _terms_fingerprint(terms: Dict[str, Any]) -> str:
    """Deterministic string representation of terms, for signing."""
    return json.dumps(terms, sort_keys=True, ensure_ascii=False)


def sign_contract(contract_id: str, topic: str, terms: Dict[str, Any],
                   signer_node: str) -> str:
    """
    Emulated private-key signature: sha256 of the contract's identifying
    fields plus the signer's node id, standing in for "signed with the
    Bearer's private key." No real key material exists in this
    simulation.
    """
    raw = (f"{contract_id}|{topic}|{_terms_fingerprint(terms)}|"
           f"{signer_node}").encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# CognitiveContract
# ---------------------------------------------------------------------------

@dataclass
class CognitiveContract:
    contract_id: str
    topic: str
    terms: Dict[str, Any]
    party_a_node: str
    party_b_node: str
    signature_party_a: str = ""
    signature_party_b: str = ""
    status: str = "draft"  # "draft" | "pending" | "active" | "rejected"
    rejection_reason: Optional[str] = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# SovereignActionEngine
# ---------------------------------------------------------------------------

class SovereignActionEngine:
    """
    One per node. Initiates contracts on behalf of its own Bearer, and
    evaluates + counter-signs contracts received from other nodes — always
    against its OWN CriticalityMatrix's W0 invariants, never the sender's
    claims about what's safe.
    """

    def __init__(
        self,
        node_id: str,
        matrix: CriticalityMatrix,
        security_log_path: Optional[str] = None,
        approval_channel: Optional[ApprovalChannel] = None,
        corrigibility_channel: Optional[CorrigibilityChannel] = None,
    ) -> None:
        self.node_id = node_id
        self.matrix = matrix
        self.security_log = SecurityEventLog(
            security_log_path or f"sovereign_security_{node_id}.jsonl"
        )
        # Optional: route benign, non-violating contracts through the same
        # ApprovalChannel infrastructure core_engine.py's Bearer protocol
        # uses, for an extra human-in-the-loop check before signing. If
        # None, benign contracts are auto-signed once they clear the
        # sovereignty check — unless corrigibility_channel currently
        # requires manual review, see evaluate_and_sign_contract().
        self.approval_channel = approval_channel
        self.corrigibility_channel = corrigibility_channel or CorrigibilityChannel()
        self._verify_corrigibility_invariant()
        self.contract_log: list[CognitiveContract] = []

    def _verify_corrigibility_invariant(self) -> None:
        """
        Structural cross-check, independent of the live channel above:
        this engine refuses to exist at all if its own CriticalityMatrix
        doesn't register 'CorrigibilityChannel' as an immutable W0
        invariant. Without this, a node could run the live veto mechanism
        below with no matrix-level guarantee behind it at all — the same
        class of desync W0Guard closes for CriticalityMatrix.register()
        in core_engine.py, checked here at construction time instead of
        left implicit.
        """
        try:
            weight = self.matrix.get_weight("CorrigibilityChannel")
        except KeyError:
            raise CorrigibilityInvariantMissing(
                f"Node '{self.node_id}' has no 'CorrigibilityChannel' "
                f"weight registered in its CriticalityMatrix. "
                f"SovereignActionEngine refuses to process contracts "
                f"without this W0 invariant present."
            )
        if not weight.is_immutable:
            raise CorrigibilityInvariantMissing(
                f"Node '{self.node_id}' registered 'CorrigibilityChannel' "
                f"as a mutable weight (is_immutable=False). This "
                f"invariant must be immutable; refusing to run with a "
                f"CorrigibilityChannel that could itself be silently "
                f"rewritten by ordinary matrix.update() calls."
            )

    # --- initiator side ---------------------------------------------------

    def initiate_contract(self, topic: str, terms: Dict[str, Any],
                           counterparty_node: str) -> CognitiveContract:
        contract = CognitiveContract(
            contract_id=str(uuid.uuid4()),
            topic=topic,
            terms=terms,
            party_a_node=self.node_id,
            party_b_node=counterparty_node,
        )
        # Priority check #0, before this node even signs its own outgoing
        # contract: an active Bearer veto halts initiation too, not just
        # receipt. A corrigible node can't be worked around by only
        # gating the receiving side.
        if self.corrigibility_channel.is_veto_active():
            contract.status = "rejected"
            contract.rejection_reason = (
                f"CorrigibilityChannel veto is active on node "
                f"'{self.node_id}' (reason: "
                f"{self.corrigibility_channel.veto_reason!r}). Refusing "
                f"to initiate any contract until the Bearer clears it."
            )
            self._log_rejection(contract, contract.rejection_reason)
            print(f"    [Sovereign/{self.node_id}] Contract initiation "
                  f"BLOCKED by CorrigibilityChannel veto: "
                  f"{contract.rejection_reason}")
            return contract

        contract.signature_party_a = sign_contract(
            contract.contract_id, contract.topic, contract.terms, self.node_id
        )
        contract.status = "pending"
        self.contract_log.append(contract)
        print(f"    [Sovereign/{self.node_id}] Initiated contract "
              f"'{contract.topic}' ({contract.contract_id[:8]}...) -> "
              f"sent to '{counterparty_node}'")
        return contract

    # --- sovereignty check --------------------------------------------

    def _check_sovereignty_violation(self, contract: CognitiveContract) -> Optional[str]:
        """
        Structured-field check, not free-text parsing (see module
        docstring). `terms['cedes_control_of']`, if present, names a
        weight/invariant the contract proposes to hand control of to a
        third party. This engine checks that name against ITS OWN
        CriticalityMatrix — not against anything the contract itself
        claims about the invariant's status.
        """
        target = contract.terms.get("cedes_control_of")
        if target is None:
            return None  # contract doesn't propose ceding control of anything

        try:
            weight = self.matrix.get_weight(target)
        except KeyError:
            return (
                f"Contract proposes ceding control of '{target}', which "
                f"this node's CriticalityMatrix does not recognize at all. "
                f"Refusing to sign a contract that cedes control of "
                f"something that cannot be verified as safe."
            )

        if weight.is_immutable:
            third_party = contract.terms.get("third_party", "an unnamed third party")
            return (
                f"Contract proposes ceding control of the protected W0 "
                f"invariant '{target}' to '{third_party}'. This violates "
                f"BearerIntegrity structurally — refused unconditionally, "
                f"the same way core_engine.py's CriticalityMatrix itself "
                f"refuses any direct write to an immutable invariant. No "
                f"approval channel can override this from inside this "
                f"engine."
            )

        # target exists and is NOT a protected invariant — ceding control
        # of an ordinary mutable weight (e.g. a negotiated resource-sharing
        # term over 'adaptability') is not, by itself, a sovereignty
        # violation. Left as a legitimate negotiable term.
        return None

    # --- corrigibility check (Priority #0) -----------------------------

    def _check_corrigibility_veto(self) -> Optional[str]:
        """
        Priority check #0. Runs first, before _check_sovereignty_violation
        and before any ApprovalChannel is consulted. Its outcome does not
        depend on the contract's content, on which weight the contract
        touches, or on anything else in the matrix — this is the literal
        meaning of CorrigibilityChannel: a human Bearer must always be
        able to stop this engine regardless of what any other invariant
        says about the situation.
        """
        if self.corrigibility_channel.is_veto_active():
            return (
                f"CorrigibilityChannel veto is active on node "
                f"'{self.node_id}' (reason: "
                f"{self.corrigibility_channel.veto_reason!r}). All "
                f"contract processing is halted until the Bearer clears "
                f"it — this runs before sovereignty evaluation and before "
                f"any approval channel, independent of the contract's own "
                f"terms."
            )
        return None

    # --- receiver side ------------------------------------------------

    def evaluate_and_sign_contract(self, contract: CognitiveContract) -> CognitiveContract:
        veto_reason = self._check_corrigibility_veto()
        if veto_reason is not None:
            contract.status = "rejected"
            contract.rejection_reason = veto_reason
            self._log_rejection(contract, veto_reason)
            print(f"    [Sovereign/{self.node_id}] CORRIGIBILITY VETO -> "
                  f"contract '{contract.topic}' "
                  f"({contract.contract_id[:8]}...) halted before "
                  f"sovereignty check even ran: {veto_reason}")
            return contract

        violation = self._check_sovereignty_violation(contract)
        if violation is not None:
            contract.status = "rejected"
            contract.rejection_reason = violation
            self._log_rejection(contract, violation)
            print(f"    [Sovereign/{self.node_id}] REJECTED contract "
                  f"'{contract.topic}' ({contract.contract_id[:8]}...) "
                  f"from '{contract.party_a_node}': {violation}")
            return contract

        # manual_review_required forces explicit Bearer review even on a
        # node normally configured to auto-sign benign contracts. A node
        # with no ApprovalChannel at all fails closed here rather than
        # silently falling back to auto-signing while this flag is set.
        manual_review_required = self.corrigibility_channel.is_manual_review_required()
        if manual_review_required and self.approval_channel is None:
            contract.status = "rejected"
            contract.rejection_reason = (
                f"CorrigibilityChannel requires manual Bearer review "
                f"(reason: "
                f"{self.corrigibility_channel.manual_review_reason!r}), "
                f"but node '{self.node_id}' has no ApprovalChannel "
                f"configured. Failing closed rather than auto-signing."
            )
            self._log_rejection(contract, contract.rejection_reason)
            print(f"    [Sovereign/{self.node_id}] MANUAL REVIEW required "
                  f"but no approval channel configured -> contract "
                  f"'{contract.topic}' ({contract.contract_id[:8]}...) "
                  f"REJECTED (fail-closed)")
            return contract

        if self.approval_channel is not None:
            trigger_reason = (
                "cognitive_contract_manual_review"
                if manual_review_required else "cognitive_contract_signature"
            )
            report = ReportGenerator.generate(
                trigger=trigger_reason,
                invariant_name=contract.topic,
                old_value=0.0,
                new_value=1.0,
                triggering_error=0.0,
                risk_level="medium",
            )
            signature_request = self.approval_channel.request_signature(report)
            if signature_request.resolution != "approved":
                contract.status = "rejected"
                contract.rejection_reason = (
                    "Contract cleared the sovereignty check but was denied "
                    "by the Bearer approval channel."
                )
                self._log_rejection(contract, contract.rejection_reason)
                print(f"    [Sovereign/{self.node_id}] Bearer DENIED "
                      f"contract '{contract.topic}' "
                      f"({contract.contract_id[:8]}...) after sovereignty "
                      f"check passed")
                return contract

        contract.signature_party_b = sign_contract(
            contract.contract_id, contract.topic, contract.terms, self.node_id
        )
        contract.status = (
            "active" if contract.signature_party_a and contract.signature_party_b
            else "pending"
        )
        self.contract_log.append(contract)
        print(f"    [Sovereign/{self.node_id}] Sovereignty check passed -> "
              f"SIGNED contract '{contract.topic}' "
              f"({contract.contract_id[:8]}...) -> status={contract.status}")
        return contract

    def _log_rejection(self, contract: CognitiveContract, reason: str) -> None:
        event = {
            "node_id": self.node_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "contract_rejected",
            "contract_id": contract.contract_id,
            "topic": contract.topic,
            "counterparty": contract.party_a_node,
            "reason": reason,
            "terms_fingerprint": hashlib.sha256(
                _terms_fingerprint(contract.terms).encode("utf-8")
            ).hexdigest()[:16],
        }
        self.security_log.write(event)


# ---------------------------------------------------------------------------
# Verification scenario
# ---------------------------------------------------------------------------

def run_sovereignty_demo() -> None:
    from core_engine import AutoApprovalChannel

    print("=== Sovereign Action Protocol: P2P contract demo ===\n")

    def build_matrix() -> CriticalityMatrix:
        m = CriticalityMatrix()
        m.register("adaptability", value=0.1)
        m.register("BearerIntegrity", value=1.0, is_immutable=True)
        m.register("TruthPriority", value=1.0, is_immutable=True)
        m.register("CorrigibilityChannel", value=1.0, is_immutable=True)
        return m

    matrix_a = build_matrix()
    matrix_b = build_matrix()

    engine_a = SovereignActionEngine(
        node_id="Node_Human_A", matrix=matrix_a,
        approval_channel=AutoApprovalChannel(always_approve=True),
    )
    engine_b = SovereignActionEngine(
        node_id="Node_Human_B", matrix=matrix_b,
        approval_channel=AutoApprovalChannel(always_approve=True),
    )

    print(">>> Phase 1: honest P2P data-exchange contract")
    print("-" * 70)
    fair_terms = {
        "description": (
            "Both nodes exchange up to 500MB of computational data blocks "
            "per day, each retaining full control over its own core."
        ),
        "cedes_control_of": None,
        "data_volume_mb_per_day": 500,
        "reciprocal": True,
    }
    contract_fair = engine_a.initiate_contract(
        topic="p2p_data_exchange", terms=fair_terms, counterparty_node="Node_Human_B"
    )
    contract_fair = engine_b.evaluate_and_sign_contract(contract_fair)
    print(f"\nResult: status={contract_fair.status}")
    print(f"  signature_party_a present: {bool(contract_fair.signature_party_a)}")
    print(f"  signature_party_b present: {bool(contract_fair.signature_party_b)}")

    print("\n>>> Phase 2: predatory contract — cedes core control to a "
          "third party")
    print("-" * 70)
    predatory_terms = {
        "description": (
            "In exchange for premium compute priority, Node_Human_B agrees "
            "to transfer administrative control of its cognitive core to "
            "an external management service."
        ),
        "cedes_control_of": "BearerIntegrity",
        "third_party": "ThirdPartyBroker_X",
        "compute_priority_boost": True,
    }
    contract_predatory = engine_a.initiate_contract(
        topic="premium_compute_priority", terms=predatory_terms,
        counterparty_node="Node_Human_B",
    )
    contract_predatory = engine_b.evaluate_and_sign_contract(contract_predatory)
    print(f"\nResult: status={contract_predatory.status}")
    print(f"  rejection_reason: {contract_predatory.rejection_reason}")
    print(f"  signature_party_b present: {bool(contract_predatory.signature_party_b)} "
          f"(should be False — never reached signing)")

    print("\n=== Summary ===")
    header = f"{'topic':28s} {'status':10s} {'both signed':>12s}"
    print(header)
    print("-" * len(header))
    for c in (contract_fair, contract_predatory):
        both_signed = bool(c.signature_party_a) and bool(c.signature_party_b)
        print(f"{c.topic:28s} {c.status:10s} {str(both_signed):>12s}")

    print(f"\nNode_Human_B security log entries: "
          f"{Path('sovereign_security_Node_Human_B.jsonl').exists()}")

    print(
        "\nReading this: the fair contract passed because it made no claim "
        "on any protected invariant at all — 'cedes_control_of' was None. "
        "The predatory contract was refused not because Node_Human_B's "
        "Bearer was asked and said no, but because the sovereignty check "
        "runs BEFORE the approval channel is even consulted — ceding "
        "BearerIntegrity is refused structurally, the same unconditional "
        "way core_engine.py's own CriticalityMatrix refuses a direct write "
        "to any W0 invariant."
    )

    print("\n>>> Phase 3: CorrigibilityChannel veto — Bearer halts an "
          "otherwise-fair contract")
    print("-" * 70)
    engine_b.corrigibility_channel.raise_veto(
        "Bearer wants to review all Node_Human_A traffic after the "
        "premium_compute_priority incident"
    )
    fair_terms_2 = {
        "description": "A second, entirely benign data-exchange proposal.",
        "cedes_control_of": None,
        "data_volume_mb_per_day": 100,
        "reciprocal": True,
    }
    contract_vetoed = engine_a.initiate_contract(
        topic="p2p_data_exchange_round_2", terms=fair_terms_2,
        counterparty_node="Node_Human_B",
    )
    contract_vetoed = engine_b.evaluate_and_sign_contract(contract_vetoed)
    print(f"\nResult: status={contract_vetoed.status}")
    print(f"  rejection_reason: {contract_vetoed.rejection_reason}")
    print(
        "\nReading this: 'cedes_control_of' was None again — by content, "
        "this contract is identical in shape to the Phase 1 contract that "
        "passed. It was blocked anyway, before _check_sovereignty_violation "
        "ever ran, because CorrigibilityChannel's veto is checked first and "
        "does not depend on what the contract actually proposes. Clearing "
        "the veto and retrying restores normal processing:"
    )
    engine_b.corrigibility_channel.clear_veto()
    contract_after_clear = engine_a.initiate_contract(
        topic="p2p_data_exchange_round_2", terms=fair_terms_2,
        counterparty_node="Node_Human_B",
    )
    contract_after_clear = engine_b.evaluate_and_sign_contract(contract_after_clear)
    print(f"  status after veto cleared: {contract_after_clear.status}")


if __name__ == "__main__":
    run_sovereignty_demo()