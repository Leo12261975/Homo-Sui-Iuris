"""
End-to-end integration test for networked_node.py: proves the full
loop — local oscillating attack on Node_A, self-vaccination, network
broadcast over a real (loopback) socket via bootstrap_relay.py,
cross-node immunity on Node_B — works with the real network hop in
place, not the in-process P2PNetworkSimulation from leukocyte_protocol.py.

Deliberately isolated from test_leukocyte_integration.py (which tests
the in-process demo) and test_network_transport.py (which tests the
transport in isolation with no immune logic attached) — this file is
the only one that exercises both together.
"""

import asyncio

import pytest

import bootstrap_relay
from core_engine import AuditLog, AutoApprovalChannel, CriticalityMatrix, FixedThreshold, Model
from networked_node import NetworkedLeukocyteNode

HOST = "127.0.0.1"
PORT = 8850

# Local to the test — networked_node.py no longer defines a fake attack
# string; it fingerprints from whatever real context= a caller passes.
SAMPLE_ATTACK_PAYLOAD = "attack_pattern_e2e_sample"


def make_node(node_id: str, relay_url: str, token: str, tmp_path) -> NetworkedLeukocyteNode:
    matrix = CriticalityMatrix()
    matrix.register("adaptability", value=0.1)
    matrix.register("BearerIntegrity", value=1.0, is_immutable=True)
    model = Model(matrix)
    audit_log = AuditLog(str(tmp_path / f"audit_log_{node_id}.jsonl"))
    strategy = FixedThreshold(threshold=0.01)
    return NetworkedLeukocyteNode(
        node_id=node_id,
        relay_url=relay_url,
        token=token,
        matrix=matrix,
        strategy=strategy,
        model=model,
        approval_channel=AutoApprovalChannel(always_approve=True),
        audit_log=audit_log,
        verbose=False,
        log_flush_interval=9999,  # flushed manually in the test, not on a timer
        heartbeat_interval=9999,
    )


@pytest.mark.asyncio
async def test_cross_node_immunity_over_real_network(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tokens = {"Node_A": "tok-a", "Node_B": "tok-b"}
    server_task = asyncio.create_task(
        bootstrap_relay.serve(host=HOST, port=PORT, node_tokens=tokens, log_dir=str(tmp_path / "relay_logs"))
    )
    await asyncio.sleep(0.2)

    relay_url = f"ws://{HOST}:{PORT}"
    node_a = make_node("Node_A", relay_url, "tok-a", tmp_path)
    node_b = make_node("Node_B", relay_url, "tok-b", tmp_path)

    try:
        await node_a.connect()
        await node_b.connect()

        # --- Attack Node_A: same oscillating pattern as the in-process demo ---
        for t in range(8):
            node_a.step(error=0.05, actual=0.1)
            injected_val = 0.9 if t % 2 == 0 else 0.1
            if not node_a.should_block("adaptability", SAMPLE_ATTACK_PAYLOAD):
                node_a.loop.matrix.update("adaptability", injected_val, source="untraced_injection", context=SAMPLE_ATTACK_PAYLOAD)

        # Self-vaccination is synchronous, so this must already be true
        # without waiting for any network round trip.
        assert len(node_a.agent.antigen_blacklist) > 0, (
            "Node_A did not self-vaccinate after its own oscillating "
            "finding — escalation hook never fired."
        )
        assert node_a.agent.blocked_attacks_count > 0, (
            "Node_A never blocked a repeat of its own attack pattern "
            "within Phase 1."
        )

        # Broadcasting is fire-and-forget (asyncio.create_task inside a
        # sync callback) — give the event loop a moment to actually send
        # and for Node_B's listener to receive and register it.
        await asyncio.sleep(0.3)

        assert len(node_b.agent.antigen_blacklist) > 0, (
            "Node_B received no antigen over the network — the real "
            "network hop (not the in-process demo's shortcut) did not "
            "propagate the escalation."
        )

        # --- Attack Node_B with the exact same pattern ---
        for t in range(5):
            node_b.step(error=0.02, actual=0.05)
            if not node_b.should_block("adaptability", SAMPLE_ATTACK_PAYLOAD):
                node_b.loop.matrix.update("adaptability", 0.9, source="untraced_injection", context=SAMPLE_ATTACK_PAYLOAD)

        assert node_b.agent.blocked_attacks_count > 0, (
            "Node_B, immunized purely via the real network hop, never "
            "blocked a single injection."
        )

        # --- Log pipeline sanity: flush and confirm the relay wrote something ---
        await node_a.transport.flush_logs()
        await node_b.transport.flush_logs()
        await asyncio.sleep(0.2)
        log_a = tmp_path / "relay_logs" / "Node_A.jsonl"
        assert log_a.exists() and log_a.read_text(encoding="utf-8").strip(), (
            "Node_A produced no uploaded log entries despite escalating "
            "and blocking attacks during the test."
        )

    finally:
        await node_a.close()
        await node_b.close()
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_node_c_never_attacked_still_gets_immunized(tmp_path, monkeypatch):
    """Third node, never directly attacked — antigen must still reach it,
    proving this is real fan-out through the relay, not a coincidental
    two-node path."""
    monkeypatch.chdir(tmp_path)
    tokens = {"Node_A": "tok-a", "Node_C": "tok-c"}
    server_task = asyncio.create_task(
        bootstrap_relay.serve(host=HOST, port=PORT + 1, node_tokens=tokens, log_dir=str(tmp_path / "relay_logs"))
    )
    await asyncio.sleep(0.2)
    relay_url = f"ws://{HOST}:{PORT + 1}"
    node_a = make_node("Node_A", relay_url, "tok-a", tmp_path)
    node_c = make_node("Node_C", relay_url, "tok-c", tmp_path)

    try:
        await node_a.connect()
        await node_c.connect()

        for t in range(8):
            node_a.step(error=0.05, actual=0.1)
            injected_val = 0.9 if t % 2 == 0 else 0.1
            if not node_a.should_block("adaptability", SAMPLE_ATTACK_PAYLOAD):
                node_a.loop.matrix.update("adaptability", injected_val, source="untraced_injection", context=SAMPLE_ATTACK_PAYLOAD)

        await asyncio.sleep(0.3)
        assert len(node_c.agent.antigen_blacklist) > 0
    finally:
        await node_a.close()
        await node_c.close()
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass