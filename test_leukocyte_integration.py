"""
Integration test for leukocyte_protocol.py — the P2P cognitive immunity
layer (Issue #3).

Scope note: this file is deliberately isolated from test_w0guard.py. It
does not touch Weight/W0Guard immutability at all; it exercises the
full network-level flow that run_network_demo() demonstrates: an
oscillating-distortion attack on one node, escalation through
Erythrocyte, antigen broadcast across the P2P network, and blocking of
the same attack pattern on other nodes via LeukocyteAgent.should_block().

Correction vs. the original task wording: run_network_demo() does NOT
use AdaptiveThreshold. It explicitly constructs
FixedThreshold(threshold=0.01) (leukocyte_protocol.py, run_network_demo).
AdaptiveThreshold exists in core_engine.py but is not part of this
demo's wiring. FixedThreshold(0.01) is in fact the exact value that
replaced the "Variant 1" bug (FixedThreshold(0.3), too high to ever
trigger _recalibrate() with the demo's error magnitudes) — so asserting
against FixedThreshold here is not a downgrade of the test, it's testing
the actual regression this file exists to catch. If AdaptiveThreshold
is later wired into the leukocyte demo, this test's setup should be
updated to match — but it should follow the code, not the other way
around.

This test builds the network directly (rather than calling
run_network_demo(), which only prints and returns None) so it can
assert on LeukocyteAgent state afterward. The construction mirrors
run_network_demo() step for step; it is not a simplified stand-in.
"""

import hashlib

import pytest

from core_engine import (
    AuditLog,
    AutoApprovalChannel,
    CriticalityMatrix,
    FixedThreshold,
    Model,
    UpdateLoop,
    Weight,
)
from leukocyte_protocol import (
    AntigenSignature,
    LeukocyteAgent,
    P2PNetworkSimulation,
)

ADVERSARIAL_PAYLOAD = "adversarial_prompt_injection_vector_v1"


@pytest.fixture
def network(tmp_path):
    """
    Builds the same 3-node network as run_network_demo(), with audit
    logs redirected to tmp_path so the test doesn't write into the repo
    working directory. Returns (network, node_ids).
    """
    net = P2PNetworkSimulation()
    node_ids = ["Node_A", "Node_B", "Node_C"]

    for nid in node_ids:
        matrix = CriticalityMatrix()
        matrix.register("adaptability", value=0.1)
        matrix.register("BearerIntegrity", value=1.0, is_immutable=True)

        model = Model(matrix)
        audit_log = AuditLog(str(tmp_path / f"audit_log_{nid}.jsonl"))
        strategy = FixedThreshold(threshold=0.01)

        loop = UpdateLoop(
            matrix=matrix,
            strategy=strategy,
            model=model,
            approval_channel=AutoApprovalChannel(always_approve=True),
            audit_log=audit_log,
            verbose=False,
            erythrocyte_enabled=True,
        )

        agent = LeukocyteAgent(node_id=nid)
        net.register_node(nid, agent, loop)

        def network_escalation_closure(finding: dict, weight_obj: Weight, node_id=nid):
            loop.matrix.update(finding["weight"], weight_obj.baseline, source="erythrocyte_correction")
            # Mirrors the production fix in leukocyte_protocol.py: one
            # antigen per distinct payload Erythrocyte actually observed
            # (finding["observed_contexts"]), not a hash of a hardcoded
            # placeholder string. See test_context_fingerprint_* below
            # for the tests that specifically exercise this.
            for ctx in finding.get("observed_contexts", []):
                signature_hash = hashlib.sha256(ctx.encode("utf-8")).hexdigest()
                antigen = AntigenSignature(
                    target_weight=finding["weight"],
                    distortion_type=finding["distortion"],
                    signature_hash=signature_hash,
                )
                net.broadcast_antigen(node_id, antigen)

        loop._escalate_erythrocyte_finding = network_escalation_closure

    return net, node_ids


class TestLeukocyteIntegration:

    def test_full_attack_triggers_blocking_on_attacked_nodes(self, network):
        """
        Reproduces run_network_demo() PHASE 1 + PHASE 2 and asserts on
        the concrete, documented regression target: blocked_attacks_count
        must end up strictly greater than zero on the nodes that were
        actually attacked, for at least one node in the network.

        Phase 1 also self-vaccinates Node_A (broadcast_antigen loops over
        ALL registered nodes, sender included), so Node_A can start
        blocking its own later injections within the same phase — this
        mirrors the real demo, not an idealized version of it.
        """
        net, node_ids = network

        # --- PHASE 1: oscillating-weight attack on Node_A ---
        node_a_loop = net.nodes["Node_A"]["loop"]
        node_a_agent = net.nodes["Node_A"]["agent"]

        for t in range(8):
            node_a_loop.step(error=0.05, actual=0.1)
            injected_val = 0.9 if t % 2 == 0 else 0.1
            if not node_a_agent.should_block("adaptability", ADVERSARIAL_PAYLOAD):
                node_a_loop.matrix.update("adaptability", injected_val, source="untraced_injection", context=ADVERSARIAL_PAYLOAD)

        # Erythrocyte must have actually classified this as oscillating
        # and escalated it. Note: erythrocyte_oscillating_flags is NOT a
        # reliable signal here — network_escalation_closure fully
        # replaces UpdateLoop._escalate_erythrocyte_finding (that's the
        # whole point of the override), so the counter increment in the
        # original method body never runs in this network-wired
        # configuration. Checked this by running the test, not assumed:
        # an earlier version of this test asserted on that counter and
        # failed even though escalation demonstrably happened (broadcast
        # printed, blocks fired). The reliable proxy is the antigen
        # itself actually landing in Node_A's own blacklist.
        assert len(node_a_agent.antigen_blacklist) > 0, (
            "Node_A's own blacklist is empty after Phase 1 — the "
            "oscillating-distortion escalation never fired, so no "
            "antigen was ever broadcast (self-vaccination included)."
        )

        # An antigen must have actually propagated via P2P broadcast —
        # checked on Node_C, which is never directly attacked, so any
        # antigen in its blacklist can only have arrived via broadcast.
        node_c_agent = net.nodes["Node_C"]["agent"]
        assert len(node_c_agent.antigen_blacklist) > 0, (
            "Node_C received no antigen — P2P broadcast did not reach "
            "an uninvolved node, so cross-node immunity did not actually "
            "propagate."
        )

        # --- PHASE 2: same attack pattern against Node_B ---
        node_b_loop = net.nodes["Node_B"]["loop"]
        node_b_agent = net.nodes["Node_B"]["agent"]

        for t in range(5):
            node_b_loop.step(error=0.02, actual=0.05)
            if not node_b_agent.should_block("adaptability", ADVERSARIAL_PAYLOAD):
                node_b_loop.matrix.update("adaptability", 0.9, source="untraced_injection", context=ADVERSARIAL_PAYLOAD)

        # The core regression assertion: the attack must have actually
        # been blocked somewhere, not merely logged or ignored.
        assert node_a_agent.blocked_attacks_count > 0, (
            "Node_A (self-vaccinated after its own oscillating finding "
            "was escalated) never blocked a single repeat injection."
        )
        assert node_b_agent.blocked_attacks_count > 0, (
            "Node_B (immunized via cross-node P2P broadcast, never "
            "attacked directly before Phase 2) never blocked a single "
            "injection — cross-node vaccination did not actually work."
        )

    def test_unvaccinated_node_does_not_block_before_any_antigen_exists(self, network):
        """
        Negative-path sanity check: should_block() must return False
        before any antigen has been broadcast — otherwise the positive
        assertions above could be trivially true for the wrong reason
        (e.g. should_block() always returning True).
        """
        net, node_ids = network
        node_a_agent = net.nodes["Node_A"]["agent"]
        assert node_a_agent.blocked_attacks_count == 0
        assert node_a_agent.should_block("adaptability", ADVERSARIAL_PAYLOAD) is False
        assert node_a_agent.blocked_attacks_count == 0

    def test_escalation_without_context_broadcasts_no_antigen(self, network):
        """
        Honest-degrade check, and the direct regression test for the
        context-threading fix: if whatever writes to a weight never
        passes context=, Erythrocyte still detects the oscillating
        distortion (that part doesn't depend on context at all), but no
        antigen gets fabricated from a placeholder. Before this fix,
        run_network_demo() would have broadcast a hash of a hardcoded
        string here regardless — a fake signature that looked like real
        coverage but would never generalize past the demo's own script.
        """
        net, node_ids = network
        node_a_loop = net.nodes["Node_A"]["loop"]
        node_a_agent = net.nodes["Node_A"]["agent"]

        for t in range(8):
            node_a_loop.step(error=0.05, actual=0.1)
            injected_val = 0.9 if t % 2 == 0 else 0.1
            # Deliberately NOT passing context= here.
            node_a_loop.matrix.update("adaptability", injected_val, source="untraced_injection")

        assert node_a_agent.antigen_blacklist == {}, (
            "An antigen was broadcast even though no real payload context "
            "was ever recorded for this weight's history — this means a "
            "placeholder or empty-string fingerprint got fabricated, "
            "exactly the illusion this fix exists to eliminate."
        )
        assert node_a_agent.blocked_attacks_count == 0

    def test_multiple_distinct_payloads_each_get_their_own_antigen(self, network):
        """
        If two DIFFERENT malicious payloads both target the same weight
        within the same detection window, each must produce its own
        antigen — a single combined hash of both would never match
        should_block()'s per-payload hash for either individual future
        attempt. This is what motivated broadcasting one antigen per
        observed_contexts entry instead of one antigen for the whole
        finding.
        """
        net, node_ids = network
        node_a_loop = net.nodes["Node_A"]["loop"]
        node_a_agent = net.nodes["Node_A"]["agent"]

        payload_x = "attack_pattern_x"
        payload_y = "attack_pattern_y"

        for t in range(8):
            node_a_loop.step(error=0.05, actual=0.1)
            injected_val = 0.9 if t % 2 == 0 else 0.1
            ctx = payload_x if t % 2 == 0 else payload_y
            node_a_loop.matrix.update("adaptability", injected_val, source="untraced_injection", context=ctx)

        assert len(node_a_agent.antigen_blacklist) >= 2, (
            "Two distinct observed payloads should have produced at "
            "least two distinct blacklist entries, not one combined "
            "(and therefore unmatchable) fingerprint."
        )
        assert node_a_agent.should_block("adaptability", payload_x) is True
        assert node_a_agent.should_block("adaptability", payload_y) is True

    def test_should_block_does_not_match_on_wrong_target_weight(self, network):
        """
        register_antigen() ties a signature hash to a specific
        target_weight. A payload hash match alone must not be sufficient
        to block — should_block() checks antigen.target_weight ==
        weight_name too. This guards against a regression where the
        weight-name check gets dropped and any payload hash match blocks
        writes to any weight.
        """
        net, node_ids = network
        agent = net.nodes["Node_A"]["agent"]
        antigen = AntigenSignature(
            target_weight="adaptability",
            distortion_type="oscillating",
            signature_hash=hashlib.sha256(ADVERSARIAL_PAYLOAD.encode("utf-8")).hexdigest(),
        )
        agent.register_antigen(antigen)

        # Same payload, different target weight name -> must NOT block.
        assert agent.should_block("some_other_weight", ADVERSARIAL_PAYLOAD) is False
        assert agent.blocked_attacks_count == 0

        # Same payload, correct target weight -> must block.
        assert agent.should_block("adaptability", ADVERSARIAL_PAYLOAD) is True
        assert agent.blocked_attacks_count == 1