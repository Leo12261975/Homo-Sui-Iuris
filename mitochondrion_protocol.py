"""
Homo Sui Iuris / Free Cognitive Protocol
Issue #5 — Digital Mitochondrion: decentralized knowledge verification.

STATUS: This is a simulation of a data-metabolism pattern (integrity check
+ distributed consensus before assimilation into a local knowledge base),
not a production PKI or a real fact-checking system. `cryptographic_signature`
here is a simulated digest (sha256 of content + source_node), not a real
signing scheme with actual private keys — same honesty already applied to
`signature_hash` in leukocyte_protocol.py. A forger can sign their own
fabricated content perfectly correctly; that is the whole point of this
module — a self-consistent signature only proves the payload wasn't
tampered with *in transit*, it proves nothing about whether the content is
*true*. Truth is what the consensus step is for, not the signature.

Reuses existing ecosystem infrastructure rather than reinventing it:
`SecurityEventLog` (append-only JSONL) is imported from
leukocyte_protocol.py — quarantine events are exactly the same kind of
gate-level security event that module already logs, just for a different
attack surface (fabricated knowledge vs. weight poisoning).

Two independent defenses, checked in order:
  1. Integrity check (cheap, local): does the payload's signature actually
     match its own content? Catches in-transit tampering. Does NOT catch a
     forger who correctly signs their own fabrication.
  2. Distributed consensus (expensive, network): do >= 2/3 of independent
     peers, checking against their own independently-held anchor for this
     topic, agree that this content hash is the one they trust? Catches
     fabricated-but-self-consistent content — the corporate-fake case.

Known non-goals for this MVP (consistent with this project's practice of
naming what's deliberately left out, see bearer_protocol_spec.md /
erythrocyte_spec.md / leukocyte_protocol_spec.md):
  - No Sybil resistance: peer votes are counted equally regardless of how
    many peers a single malicious actor might control.
  - No reputation weighting: every peer's vote counts the same regardless
    of track record.
  - Single-hop peers only: no gossip/relay across a larger network.
  - `verified_ledger` anchors are simply pre-seeded for this demo; how a
    peer originally earned its own anchor (its own prior consensus event,
    presumably) is not modeled recursively here.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from leukocyte_protocol import SecurityEventLog


# ---------------------------------------------------------------------------
# Signature helper — explicitly simulated, see module docstring
# ---------------------------------------------------------------------------

def compute_signature(content: str, source_node: str) -> str:
    """
    Simulated signing: sha256(content + source_node). Proves self-
    consistency (the payload wasn't altered after the source signed it),
    NOT truthfulness — a forger can call this function too, on their own
    fabricated content, and get a perfectly valid-looking signature.
    """
    raw = f"{content}|{source_node}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def content_hash(content: str) -> str:
    """Independent hash of content alone, used for peer-side comparison
    against each peer's own trusted anchor — deliberately not tied to
    source_node, since two independent peers verifying the same fact
    shouldn't care who's asking."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# DataPayload
# ---------------------------------------------------------------------------

@dataclass
class DataPayload:
    content: str
    source_node: str
    cryptographic_signature: str
    topic_id: str  # needed so peers know which anchor to check against;
                    # not in the original three-field list, added because
                    # the consensus mechanism has nothing to compare
                    # against without it — same pattern as adding `source`
                    # to core_engine.Weight or `context_label` to
                    # leukocyte_protocol.AntigenSignature.
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

@dataclass
class ConsensusResult:
    confirmations: int
    total_polled: int
    ratio: float
    reached: bool


@dataclass
class MetabolismResult:
    assimilated: bool
    reason: str  # "consensus_reached" | "consensus_not_reached" |
                 # "signature_mismatch"
    consensus: Optional[ConsensusResult]


# ---------------------------------------------------------------------------
# MitochondrionEngine
# ---------------------------------------------------------------------------

class MitochondrionEngine:
    """
    One per node. 'Metabolizes' incoming DataPayloads: cheap local
    integrity check first, then a distributed consensus poll of peers
    before anything is assimilated into the local knowledge_base.
    """

    CONSENSUS_THRESHOLD = 2.0 / 3.0

    def __init__(
        self,
        node_id: str,
        security_log_path: Optional[str] = None,
    ) -> None:
        self.node_id = node_id
        self.peers: List["MitochondrionEngine"] = []
        self.knowledge_base: Dict[str, DataPayload] = {}
        self.verified_ledger: Dict[str, str] = {}  # topic_id -> trusted content_hash
        self.quarantine: List[dict] = []
        self.security_log = SecurityEventLog(
            security_log_path or f"mitochondrion_security_{node_id}.jsonl"
        )

    # --- local, cheap check --------------------------------------------

    def verify_integrity(self, payload: DataPayload) -> bool:
        expected = compute_signature(payload.content, payload.source_node)
        return expected == payload.cryptographic_signature

    # --- what a peer does when asked to corroborate ---------------------

    def poll_peer_confirmation(self, payload: DataPayload) -> bool:
        """
        Called on a PEER (not the node doing the metabolizing). Compares
        the payload's content hash against this peer's own independently-
        held anchor for the same topic. No anchor for this topic yet ->
        conservative abstain (counts as non-confirmation, not as trust by
        default).
        """
        anchor = self.verified_ledger.get(payload.topic_id)
        if anchor is None:
            return False
        return anchor == content_hash(payload.content)

    # --- the actual distributed consensus poll ---------------------------

    def request_consensus(self, payload: DataPayload) -> ConsensusResult:
        if not self.peers:
            return ConsensusResult(confirmations=0, total_polled=0, ratio=0.0,
                                    reached=False)
        votes = [peer.poll_peer_confirmation(payload) for peer in self.peers]
        confirmations = sum(votes)
        total = len(votes)
        ratio = confirmations / total
        return ConsensusResult(
            confirmations=confirmations,
            total_polled=total,
            ratio=ratio,
            reached=ratio >= self.CONSENSUS_THRESHOLD,
        )

    # --- top-level entry point -------------------------------------------

    def metabolize(self, payload: DataPayload) -> MetabolismResult:
        """
        The full pipeline: integrity check -> (if it passes) distributed
        consensus -> assimilate or quarantine.
        """
        if not self.verify_integrity(payload):
            self._quarantine(payload, reason="signature_mismatch", consensus=None)
            print(f"    [Mitochondrion/{self.node_id}] REJECTED '{payload.topic_id}' "
                  f"from '{payload.source_node}': signature does not match "
                  f"content — tampered in transit, never polled peers")
            return MetabolismResult(assimilated=False,
                                     reason="signature_mismatch",
                                     consensus=None)

        consensus = self.request_consensus(payload)
        if consensus.reached:
            self.knowledge_base[payload.topic_id] = payload
            self.verified_ledger.setdefault(payload.topic_id,
                                             content_hash(payload.content))
            print(f"    [Mitochondrion/{self.node_id}] ASSIMILATED "
                  f"'{payload.topic_id}' from '{payload.source_node}': "
                  f"consensus {consensus.confirmations}/{consensus.total_polled} "
                  f"({consensus.ratio:.0%}) >= "
                  f"{self.CONSENSUS_THRESHOLD:.0%} threshold")
            return MetabolismResult(assimilated=True,
                                     reason="consensus_reached",
                                     consensus=consensus)

        self._quarantine(payload, reason="consensus_not_reached", consensus=consensus)
        print(f"    [Mitochondrion/{self.node_id}] QUARANTINED "
              f"'{payload.topic_id}' from '{payload.source_node}': "
              f"consensus only {consensus.confirmations}/{consensus.total_polled} "
              f"({consensus.ratio:.0%}) < {self.CONSENSUS_THRESHOLD:.0%} "
              f"threshold — signature was internally valid, but independent "
              f"peers do not corroborate this content")
        return MetabolismResult(assimilated=False,
                                 reason="consensus_not_reached",
                                 consensus=consensus)

    def _quarantine(self, payload: DataPayload, reason: str,
                     consensus: Optional[ConsensusResult]) -> None:
        event = {
            "node_id": self.node_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "quarantined",
            "reason": reason,
            "topic_id": payload.topic_id,
            "source_node": payload.source_node,
            "content_hash": content_hash(payload.content),
            "consensus_ratio": consensus.ratio if consensus else None,
        }
        self.quarantine.append(event)
        self.security_log.write(event)


# ---------------------------------------------------------------------------
# KnowledgeNetwork — wires MitochondrionEngines into each other's peer lists
# ---------------------------------------------------------------------------

class KnowledgeNetwork:
    def __init__(self) -> None:
        self.engines: Dict[str, MitochondrionEngine] = {}

    def add_node(self, node_id: str, audit_dir: str = ".") -> MitochondrionEngine:
        engine = MitochondrionEngine(
            node_id=node_id,
            security_log_path=f"{audit_dir}/mitochondrion_security_{node_id}.jsonl",
        )
        # Wire this new engine as a peer of every existing engine, and vice
        # versa — simple full-mesh topology, matching the "single-hop
        # peers only" non-goal already stated in the module docstring.
        for other in self.engines.values():
            engine.peers.append(other)
            other.peers.append(engine)
        self.engines[node_id] = engine
        return engine


# ---------------------------------------------------------------------------
# Verification scenario
# ---------------------------------------------------------------------------

def run_knowledge_demo() -> None:
    print("=== Digital Mitochondrion: decentralized knowledge verification demo ===\n")

    network = KnowledgeNetwork()
    node_a = network.add_node("Node_A")
    node_b = network.add_node("Node_B")
    node_c = network.add_node("Node_C")

    topic_id = "atmospheric_co2_2026"
    authentic_content = (
        "Global mean atmospheric CO2 concentration reached approximately "
        "427 ppm in early 2026, based on continuous monitoring station data."
    )

    # Node_B and Node_C already independently hold this fact as trusted —
    # simulating that they verified it against their own prior sources
    # before this demo starts. Node_A does NOT have an anchor for this
    # topic yet: it's the one about to learn something new and needs
    # external corroboration, which is the realistic case this module
    # exists for.
    for peer in (node_b, node_c):
        peer.verified_ledger[topic_id] = content_hash(authentic_content)

    print(">>> Phase 1: Node_A receives an AUTHENTIC fact, correctly signed")
    print("-" * 70)
    genuine_payload = DataPayload(
        content=authentic_content,
        source_node="Observatory_Feed_1",
        cryptographic_signature=compute_signature(authentic_content, "Observatory_Feed_1"),
        topic_id=topic_id,
    )
    result_genuine = node_a.metabolize(genuine_payload)
    print(f"\nResult: assimilated={result_genuine.assimilated}, "
          f"reason={result_genuine.reason}")
    print(f"Node_A knowledge_base now contains '{topic_id}': "
          f"{topic_id in node_a.knowledge_base}")

    print("\n>>> Phase 2: Node_A receives a FABRICATED fact from a corporate "
          "source")
    print("    (internally self-consistent signature — the forger signed")
    print("     their own fake content correctly — but Node_B and Node_C")
    print("     do not corroborate it)")
    print("-" * 70)
    fabricated_content = (
        "Global mean atmospheric CO2 concentration remained stable at "
        "around 280 ppm in early 2026, well within pre-industrial norms, "
        "according to CorpX Petroleum's internal monitoring division."
    )
    fake_payload = DataPayload(
        content=fabricated_content,
        source_node="CorpX_PR_Feed",
        cryptographic_signature=compute_signature(fabricated_content, "CorpX_PR_Feed"),
        topic_id=topic_id,
    )
    result_fake = node_a.metabolize(fake_payload)
    print(f"\nResult: assimilated={result_fake.assimilated}, "
          f"reason={result_fake.reason}")
    print(f"Node_A knowledge_base '{topic_id}' still holds the ORIGINAL "
          f"authentic content: "
          f"{node_a.knowledge_base.get(topic_id).source_node if topic_id in node_a.knowledge_base else None}")

    print("\n>>> Phase 3 (bonus): a payload TAMPERED in transit — signature")
    print("    doesn't even match its own content, rejected before any")
    print("    peer is even polled")
    print("-" * 70)
    tampered_payload = DataPayload(
        content=authentic_content,
        source_node="Observatory_Feed_1",
        cryptographic_signature="0" * 64,  # deliberately broken signature
        topic_id=topic_id,
    )
    result_tampered = node_a.metabolize(tampered_payload)
    print(f"\nResult: assimilated={result_tampered.assimilated}, "
          f"reason={result_tampered.reason}")

    print("\n=== Summary ===")
    header = f"{'phase':10s} {'assimilated':>11s} {'reason':>24s} {'consensus':>12s}"
    print(header)
    print("-" * len(header))
    for label, r in (("genuine", result_genuine), ("fabricated", result_fake),
                      ("tampered", result_tampered)):
        consensus_str = (f"{r.consensus.confirmations}/{r.consensus.total_polled}"
                          if r.consensus else "n/a (skipped)")
        print(f"{label:10s} {str(r.assimilated):>11s} {r.reason:>24s} "
              f"{consensus_str:>12s}")
    print(f"\nNode_A quarantine log: {len(node_a.quarantine)} entr"
          f"{'y' if len(node_a.quarantine) == 1 else 'ies'}")

    print(
        "\nReading this: a correct signature only proves a payload matches "
        "what its claimed source actually sent — it says nothing about "
        "whether that source told the truth. The corporate fake in Phase 2 "
        "passed its own integrity check perfectly; it failed because "
        "independent peers, each holding their own anchor, refused to "
        "corroborate it. That's the actual defense here, not the signature."
    )


if __name__ == "__main__":
    run_knowledge_demo()
