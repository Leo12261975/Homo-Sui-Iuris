"""
Reconnect/backoff test for node_transport.py's run_forever().

Two things are honest failure modes if reconnect is broken and this
test would catch both:
  1. The client silently stops trying after the first drop (no error,
     just nothing ever happens again) — caught by asserting
     wait_connected() actually completes after the relay comes back.
  2. The client "reconnects" in the sense of a fresh TCP handshake but
     the resulting session isn't actually wired back into the running
     antigen-consuming loop — caught by proving a real antigen sent by
     a second peer AFTER the restart is received by on_antigen().

Deliberately does NOT assert exact backoff timing (that would make the
test flaky under CI load) — only that reconnection happens within a
generous bound, and that the client does not spin hot (busy-loop) while
the relay is down.
"""

import asyncio

import pytest

import bootstrap_relay
from node_transport import AuthenticationError, NodeTransport

HOST = "127.0.0.1"
PORT = 8920


async def start_relay(tokens: dict, port: int, log_dir) -> asyncio.Task:
    task = asyncio.create_task(
        bootstrap_relay.serve(host=HOST, port=port, node_tokens=tokens, log_dir=str(log_dir))
    )
    await asyncio.sleep(0.2)  # let it bind before anyone tries to connect
    return task


async def stop_relay(task: asyncio.Task) -> None:
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_client_reconnects_after_relay_restart(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tokens = {"Tester_R": "tok-r", "Tester_S": "tok-s"}
    log_dir = tmp_path / "relay_logs"

    server_task = await start_relay(tokens, PORT, log_dir)

    received = []

    async def on_antigen(payload):
        received.append(payload)

    client = NodeTransport(f"ws://{HOST}:{PORT}", "Tester_R", "tok-r")
    run_task = asyncio.create_task(
        client.run_forever(
            on_antigen=on_antigen,
            initial_backoff=0.1,   # fast for the test; production default is 1.0
            max_backoff=0.5,
            backoff_factor=2.0,
            heartbeat_interval=9999,   # not what this test is exercising
            flush_interval=9999,
        )
    )

    try:
        # --- 1. Confirm the initial connection actually happens ---
        await asyncio.wait_for(client.wait_connected(), timeout=2)
        assert client._connected_event.is_set()

        # --- 2. Kill the relay out from under the live session ---
        await stop_relay(server_task)

        # The client's incoming_antigens() loop should notice the drop
        # on its own (ConnectionClosed propagating out of `async for`),
        # which run_forever() catches and turns into close() + backoff.
        # Poll instead of a fixed sleep — reconnect timing depends on
        # how fast the OS reports the closed socket, not just our
        # backoff constant.
        for _ in range(50):  # up to ~2.5s at 50ms steps
            if not client._connected_event.is_set():
                break
            await asyncio.sleep(0.05)
        assert not client._connected_event.is_set(), (
            "client still thinks it's connected after the relay was killed — "
            "the drop was never detected, so reconnect logic never engages."
        )

        # --- 3. run_forever must still be alive, retrying in the background ---
        # (not crashed, not silently exited)
        assert not run_task.done(), (
            "run_forever() exited instead of retrying after a transient "
            "connection drop — a killed relay should trigger backoff, not "
            "give up."
        )

        # --- 4. Bring the relay back up on the SAME port ---
        server_task = await start_relay(tokens, PORT, log_dir)

        # The client's own backoff loop — not this test — must notice
        # the relay is back and reconnect unattended.
        await asyncio.wait_for(client.wait_connected(), timeout=5)
        assert client._connected_event.is_set()

        # --- 5. Prove the recovered session is actually USABLE, not just ---
        # --- a successful handshake that leads nowhere. ---
        other = NodeTransport(f"ws://{HOST}:{PORT}", "Tester_S", "tok-s")
        await other.connect()
        try:
            await other.send_antigen({
                "target_weight": "adaptability",
                "distortion_type": "oscillating",
                "signature_hash": "deadbeef-reconnect-test",
            })
            for _ in range(40):  # up to ~2s
                if received:
                    break
                await asyncio.sleep(0.05)
        finally:
            await other.close()

        assert len(received) == 1, (
            "reconnected session did not actually relay a real antigen — "
            "handshake succeeded but the recovered connection isn't wired "
            "back into on_antigen()."
        )
        assert received[0]["signature_hash"] == "deadbeef-reconnect-test"

    finally:
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, AuthenticationError):
            pass
        await stop_relay(server_task)


@pytest.mark.asyncio
async def test_auth_failure_does_not_retry_forever(tmp_path, monkeypatch):
    """A rejected token is not a transient failure — run_forever() must
    surface AuthenticationError immediately instead of looping backoff
    forever against a relay that will never accept this token."""
    monkeypatch.chdir(tmp_path)
    tokens = {"Tester_R": "tok-r"}
    log_dir = tmp_path / "relay_logs"
    server_task = await start_relay(tokens, PORT + 1, log_dir)

    client = NodeTransport(f"ws://{HOST}:{PORT + 1}", "Tester_R", "definitely-wrong-token")

    async def on_antigen(_payload):
        pass

    try:
        with pytest.raises(AuthenticationError):
            await asyncio.wait_for(
                client.run_forever(
                    on_antigen=on_antigen,
                    initial_backoff=0.05,
                    max_backoff=0.2,
                ),
                timeout=2,  # if this times out instead, run_forever is retrying forever — bug
            )
    finally:
        await stop_relay(server_task)


@pytest.mark.asyncio
async def test_reconnect_callbacks_fire_in_order(tmp_path, monkeypatch):
    """The three visibility callbacks added for the silent-reconnect bug
    (dry run, 2026-07-18) must fire in the right order around a real
    drop+recovery: on_disconnected() when the session actually breaks,
    on_reconnecting(sleep_for) before each backoff sleep, on_reconnected()
    only once the NEW session's handshake actually succeeds — not just
    on any retry attempt."""
    monkeypatch.chdir(tmp_path)
    tokens = {"Tester_R": "tok-r"}
    log_dir = tmp_path / "relay_logs"
    port = PORT + 2  # separate port from the other tests in this file

    server_task = await start_relay(tokens, port, log_dir)

    events = []

    async def on_antigen(_payload):
        pass

    client = NodeTransport(f"ws://{HOST}:{port}", "Tester_R", "tok-r")
    run_task = asyncio.create_task(
        client.run_forever(
            on_antigen=on_antigen,
            initial_backoff=0.1,
            max_backoff=0.5,
            backoff_factor=2.0,
            heartbeat_interval=9999,
            flush_interval=9999,
            on_disconnected=lambda: events.append("disconnected"),
            on_reconnecting=lambda sleep_for: events.append(("reconnecting", sleep_for)),
            on_reconnected=lambda: events.append("reconnected"),
        )
    )

    try:
        await asyncio.wait_for(client.wait_connected(), timeout=2)
        assert events == [], (
            "a callback fired on the very first connection — these are "
            "reconnect signals, not connect signals, and firing here would "
            "show a bogus 'Reconnected' message on program startup."
        )

        await stop_relay(server_task)
        for _ in range(50):
            if not client._connected_event.is_set():
                break
            await asyncio.sleep(0.05)
        assert not client._connected_event.is_set()

        for _ in range(20):
            if len(events) >= 2:
                break
            await asyncio.sleep(0.05)
        assert events[0] == "disconnected", f"expected 'disconnected' first, got {events}"
        assert events[1][0] == "reconnecting", f"expected 'reconnecting' second, got {events}"
        assert "reconnected" not in events, (
            "on_reconnected fired before the relay even came back — "
            "it must only fire after a real successful handshake."
        )

        server_task = await start_relay(tokens, port, log_dir)
        await asyncio.wait_for(client.wait_connected(), timeout=5)
        assert client._connected_event.is_set()

        for _ in range(40):
            if "reconnected" in events:
                break
            await asyncio.sleep(0.05)
        assert events.count("reconnected") == 1, (
            f"expected on_reconnected exactly once after recovery, got: {events}"
        )
        assert events[-1] == "reconnected", (
            f"on_reconnected should be the last event so far, got: {events}"
        )
        assert events.count("disconnected") == 1, (
            f"on_disconnected should have fired exactly once for one real drop, got: {events}"
        )

    finally:
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, AuthenticationError):
            pass
        await stop_relay(server_task)