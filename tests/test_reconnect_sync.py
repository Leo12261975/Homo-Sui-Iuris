"""
Network connectivity + state-sync tests for the relay/node pair.

The dry run's second finding was that a node can silently lose its place after a
network blip; more generally, a node that is offline (disconnected, or simply
joined late) permanently misses any antigen broadcast during that window. These
tests pin the fix: bootstrap_relay.Relay replays its known antigens to every
node on connect, so connectivity recovery also recovers *state*.

Real loopback sockets against a real relay, one process, fully deterministic.
"""

import asyncio

import pytest

import bootstrap_relay
from core_engine import AuditLog, AutoApprovalChannel, CriticalityMatrix, FixedThreshold, Model
from networked_node import NetworkedLeukocyteNode
from node_transport import NodeTransport

HOST = "127.0.0.1"
ATTACK_PAYLOAD = "adversarial_prompt_injection_vector_v1"


def make_node(node_id, relay_url, token, tmp_path, **kw):
    matrix = CriticalityMatrix()
    matrix.register("adaptability", value=0.1)
    matrix.register("BearerIntegrity", value=1.0, is_immutable=True)
    return NetworkedLeukocyteNode(
        node_id=node_id,
        relay_url=relay_url,
        token=token,
        matrix=matrix,
        strategy=FixedThreshold(threshold=0.01),
        model=Model(matrix),
        approval_channel=AutoApprovalChannel(always_approve=True),
        audit_log=AuditLog(str(tmp_path / f"audit_log_{node_id}.jsonl")),
        verbose=False,
        log_flush_interval=9999,
        heartbeat_interval=9999,
        **kw,
    )


def drive_attack(node, payload=ATTACK_PAYLOAD):
    for t in range(8):
        node.step(error=0.05, actual=0.1)
        injected = 0.9 if t % 2 == 0 else 0.1
        if not node.should_block("adaptability", payload):
            node.loop.matrix.update("adaptability", injected, source="untraced_injection", context=payload)


async def _start_relay(port, tokens, tmp_path):
    task = asyncio.create_task(
        bootstrap_relay.serve(host=HOST, port=port, node_tokens=tokens, log_dir=str(tmp_path / "relay_logs"))
    )
    await asyncio.sleep(0.2)
    return task


async def _stop(task):
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_late_joiner_is_synced_with_prior_antigens(tmp_path, monkeypatch):
    """A node that connects AFTER an antigen was broadcast still gets it — the
    relay replays known antigens on connect, so late joiners aren't blind to
    attacks they missed."""
    monkeypatch.chdir(tmp_path)
    port = 8881
    tokens = {"Node_A": "a", "Node_LATE": "l"}
    relay = await _start_relay(port, tokens, tmp_path)
    url = f"ws://{HOST}:{port}"

    attacker = make_node("Node_A", url, "a", tmp_path)
    try:
        await attacker.connect()
        drive_attack(attacker)
        await asyncio.sleep(0.3)
        assert attacker.agent.antigen_blacklist  # broadcast happened

        # Now — after the broadcast — a fresh node joins.
        late = make_node("Node_LATE", url, "l", tmp_path)
        await late.connect()
        await asyncio.sleep(0.3)  # let the on-connect sync arrive

        assert late.agent.antigen_blacklist, (
            "late joiner was not synced with the antigen broadcast before it connected"
        )
        assert late.should_block("adaptability", ATTACK_PAYLOAD) is True
        await late.close()
    finally:
        await attacker.close()
        await _stop(relay)


@pytest.mark.asyncio
async def test_reconnecting_node_resyncs_antigen_missed_while_offline(tmp_path, monkeypatch):
    """The reconnect-visibility scenario, but checking STATE not just callbacks:
    a node drops, an antigen is broadcast while it is offline, and on reconnect
    it catches up via sync — no permanent blind spot."""
    monkeypatch.chdir(tmp_path)
    port = 8882
    tokens = {"Node_A": "a", "Node_B": "b"}
    relay = await _start_relay(port, tokens, tmp_path)
    url = f"ws://{HOST}:{port}"

    events = []
    node_b = make_node(
        "Node_B", url, "b", tmp_path,
        on_disconnected=lambda: events.append("disconnected"),
        on_reconnected=lambda: events.append("reconnected"),
    )
    attacker = make_node("Node_A", url, "a", tmp_path)
    try:
        await node_b.connect()
        await attacker.connect()
        assert not node_b.agent.antigen_blacklist  # nothing yet

        # Drop the relay so node_b goes offline; the attacker instance is torn
        # down too, but the relay will remember the antigen once it's back.
        await _stop(relay)
        for _ in range(50):
            await asyncio.sleep(0.1)
            if "disconnected" in events:
                break
        assert "disconnected" in events

        # Relay returns; a (reconnected) attacker broadcasts while node_b may
        # still be mid-reconnect.
        relay = await _start_relay(port, tokens, tmp_path)
        await attacker.close()
        attacker2 = make_node("Node_A", url, "a", tmp_path)
        await attacker2.connect()
        drive_attack(attacker2)

        # node_b reconnects and must end up immunized — whether it caught the
        # live broadcast or the on-connect sync.
        for _ in range(80):
            await asyncio.sleep(0.1)
            if node_b.agent.antigen_blacklist:
                break
        assert "reconnected" in events, "reconnect was silent"
        assert node_b.agent.antigen_blacklist, (
            "node_b did not resync the antigen it missed while offline"
        )
        await attacker2.close()
    finally:
        await node_b.close()
        await attacker.close()
        await _stop(relay)


@pytest.mark.asyncio
async def test_relay_sync_dedupes_and_is_bounded(tmp_path, monkeypatch):
    """Two broadcasts of the same signature are remembered once; a raw
    transport connecting afterward is synced with exactly the distinct set."""
    monkeypatch.chdir(tmp_path)
    port = 8883
    tokens = {"Node_A": "a", "Probe": "p"}
    relay = await _start_relay(port, tokens, tmp_path)
    url = f"ws://{HOST}:{port}"

    sender = NodeTransport(url, "Node_A", "a")
    try:
        await sender.connect()
        payload = {"target_weight": "adaptability", "distortion_type": "oscillating", "signature_hash": "sig-1"}
        await sender.send_antigen(payload)
        await sender.send_antigen(dict(payload))  # exact duplicate
        await sender.send_antigen({**payload, "signature_hash": "sig-2"})
        await asyncio.sleep(0.2)

        # A raw probe connects late and collects whatever the relay syncs to it.
        probe = NodeTransport(url, "Probe", "p")
        await probe.connect()
        synced = []

        async def collect():
            async for p in probe.incoming_antigens():
                synced.append(p)

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.3)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        hashes = sorted(p["signature_hash"] for p in synced)
        assert hashes == ["sig-1", "sig-2"], f"expected deduped sync of 2 antigens, got {hashes}"
        await probe.close()
    finally:
        await sender.close()
        await _stop(relay)
