"""
Sanity test for bootstrap_relay.py + node_transport.py — proves the
relay/client pair actually moves data over a real (loopback) socket,
not just that the code imports cleanly.
"""

import asyncio
import json
from pathlib import Path

import pytest

import bootstrap_relay
from node_transport import NodeTransport

HOST = "127.0.0.1"
PORT = 8799


@pytest.mark.asyncio
async def test_antigen_relay_and_log_batch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    tokens = {"Tester_A": "tok-a", "Tester_B": "tok-b"}
    server_task = asyncio.create_task(
        bootstrap_relay.serve(host=HOST, port=PORT, node_tokens=tokens)
    )
    await asyncio.sleep(0.2)  # let the server bind

    try:
        client_a = NodeTransport(f"ws://{HOST}:{PORT}", "Tester_A", "tok-a")
        client_b = NodeTransport(f"ws://{HOST}:{PORT}", "Tester_B", "tok-b")
        await client_a.connect()
        await client_b.connect()

        # B listens for relayed antigens in the background.
        received = []

        async def listen():
            async for payload in client_b.incoming_antigens():
                received.append(payload)
                break

        listener = asyncio.create_task(listen())
        await asyncio.sleep(0.1)

        await client_a.send_antigen({
            "target_weight": "adaptability",
            "distortion_type": "oscillating",
            "signature_hash": "deadbeef",
        })

        await asyncio.wait_for(listener, timeout=2)
        assert len(received) == 1
        assert received[0]["target_weight"] == "adaptability"

        # Log batch: A queues two entries and flushes.
        client_a.queue_log({"event": "blocked", "weight": "adaptability"})
        client_a.queue_log({"event": "blocked", "weight": "adaptability"})
        await client_a.flush_logs()
        await asyncio.sleep(0.2)  # let the server write the file

        log_path = tmp_path / "relay_logs" / "Tester_A.jsonl"
        assert log_path.exists(), "relay did not write the log batch to disk"
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["event"] == "blocked"

        await client_a.close()
        await client_b.close()
    finally:
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_wrong_token_is_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tokens = {"Tester_A": "tok-a"}
    server_task = asyncio.create_task(
        bootstrap_relay.serve(host=HOST, port=PORT + 1, node_tokens=tokens)
    )
    await asyncio.sleep(0.2)
    try:
        bad_client = NodeTransport(f"ws://{HOST}:{PORT + 1}", "Tester_A", "wrong-token")
        with pytest.raises(Exception):
            await bad_client.connect()
    finally:
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass