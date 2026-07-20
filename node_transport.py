"""
Homo Sui Iuris / Free Cognitive Protocol — client-side network transport
for external testnet nodes.

Deliberately outbound-only: this is what makes an ordinary volunteer's
home machine usable without them touching router settings. The node
never listens for inbound connections; it opens one WebSocket to
bootstrap_relay.py and keeps it alive.

This module intentionally does NOT know anything about
CriticalityMatrix, LeukocyteAgent, or Erythrocyte — it only moves JSON
payloads. The wiring between "an antigen arrived over the network" and
"call agent.register_antigen(...)" belongs in the process that owns
both the transport and the local LeukocyteAgent, not here.

Reconnect policy: `run_forever()` owns the full connect -> consume ->
reconnect lifecycle with exponential backoff + jitter. The lower-level
methods (`connect`, `close`, `send_antigen`, `incoming_antigens`, ...)
remain available directly for callers that want to manage the loop
themselves (e.g. tests) or embed it in a different event loop shape.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

import websockets

log = logging.getLogger("node_transport")

DEFAULT_INITIAL_BACKOFF = 1.0     # seconds, first retry after a drop
DEFAULT_MAX_BACKOFF = 60.0        # seconds, backoff ceiling
DEFAULT_BACKOFF_FACTOR = 2.0      # exponential multiplier
DEFAULT_JITTER = 0.3              # +/- 30% randomization, avoids thundering herd
DEFAULT_HEARTBEAT_INTERVAL = 30.0
DEFAULT_FLUSH_INTERVAL = 15.0

# Close codes the relay sends for handshake problems (see bootstrap_relay.py
# _authenticate). 4003 = auth failed — retrying with the same token will
# never succeed, so this is treated as fatal, not transient.
_AUTH_FAILURE_CODE = 4003
_PROTOCOL_ERROR_CODES = {4000, 4001}  # bad json / didn't send hello first


class AuthenticationError(ConnectionError):
    """Raised when the relay rejects the node's token. Not retryable —
    the caller needs a new/corrected token before trying again."""


class NodeTransport:
    def __init__(self, relay_url: str, node_id: str, token: str) -> None:
        self.relay_url = relay_url
        self.node_id = node_id
        self.token = token
        self._ws: Optional["websockets.WebSocketClientProtocol"] = None
        self._log_buffer: List[Dict[str, Any]] = []
        # Set only while a real authenticated session is live. Lets a
        # caller that kicks off run_forever() as a background task still
        # await first-connection success/failure at startup, the same
        # way a direct `await connect()` used to behave.
        self._connected_event = asyncio.Event()

    async def wait_connected(self) -> None:
        """Blocks until the current (or next) session completes its
        handshake. Intended for startup: `asyncio.wait_for(transport.wait_connected(), timeout=...)`
        right after launching run_forever() as a background task."""
        await self._connected_event.wait()

    async def connect(self) -> None:
        self._connected_event.clear()
        self._ws = await websockets.connect(self.relay_url)
        await self._ws.send(json.dumps({
            "type": "hello", "node_id": self.node_id, "token": self.token,
        }))
        try:
            ack_raw = await self._ws.recv()
        except websockets.ConnectionClosed as e:
            # Prefer the non-deprecated accessors; e.code alone triggers
            # a DeprecationWarning on newer websockets versions (13.1+).
            rcvd = getattr(e, "rcvd", None)
            code = getattr(rcvd, "code", None) if rcvd is not None else None
            if code is None:
                code = getattr(e, "close_code", None)
            if code is None:
                code = getattr(e, "code", None)  # last-resort fallback for older websockets
            if code == _AUTH_FAILURE_CODE:
                raise AuthenticationError(f"relay rejected token for node_id={self.node_id!r}") from e
            if code in _PROTOCOL_ERROR_CODES:
                raise AuthenticationError(f"relay rejected handshake (code {code})") from e
            raise ConnectionError(f"connection closed during handshake: {e}") from e
        ack = json.loads(ack_raw)
        if ack.get("type") != "hello_ack":
            raise ConnectionError(f"handshake failed: {ack}")
        log.info("connected to relay as %s", self.node_id)
        self._connected_event.set()

    async def close(self) -> None:
        self._connected_event.clear()
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def send_antigen(self, antigen_payload: Dict[str, Any]) -> None:
        if self._ws is None:
            raise ConnectionError("not connected")
        await self._ws.send(json.dumps({"type": "antigen", "payload": antigen_payload}))

    def queue_log(self, entry: Dict[str, Any]) -> None:
        self._log_buffer.append(entry)

    async def flush_logs(self) -> None:
        if not self._log_buffer or self._ws is None:
            return
        batch, self._log_buffer = self._log_buffer, []
        try:
            await self._ws.send(json.dumps({"type": "log_batch", "payload": batch}))
        except websockets.ConnectionClosed:
            # Connection dropped between the check above and the send —
            # put the batch back so it goes out on the next successful
            # flush after reconnect, instead of silently losing entries.
            self._log_buffer = batch + self._log_buffer
            raise

    async def incoming_antigens(self) -> AsyncIterator[Dict[str, Any]]:
        """Yields payload dicts for every antigen relayed from other
        nodes. Runs until the connection drops; low-level callers are
        responsible for reconnect/backoff around this — run_forever()
        below does that automatically."""
        if self._ws is None:
            raise ConnectionError("not connected")
        async for raw in self._ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "antigen":
                yield msg.get("payload", {})

    async def run_heartbeat(self, interval: float = DEFAULT_HEARTBEAT_INTERVAL) -> None:
        while True:
            await asyncio.sleep(interval)
            if self._ws is not None:
                await self._ws.send(json.dumps({"type": "heartbeat"}))

    async def _flush_loop(self, interval: float = DEFAULT_FLUSH_INTERVAL) -> None:
        while True:
            await asyncio.sleep(interval)
            await self.flush_logs()

    # ------------------------------------------------------------------
    # High-level lifecycle: connect, consume, reconnect with backoff.
    # ------------------------------------------------------------------

    async def run_forever(
        self,
        on_antigen: Callable[[Dict[str, Any]], Awaitable[None]],
        *,
        initial_backoff: float = DEFAULT_INITIAL_BACKOFF,
        max_backoff: float = DEFAULT_MAX_BACKOFF,
        backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
        jitter: float = DEFAULT_JITTER,
        heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL,
        flush_interval: float = DEFAULT_FLUSH_INTERVAL,
        stop_event: Optional[asyncio.Event] = None,
        on_disconnected: Optional[Callable[[], None]] = None,
        on_reconnecting: Optional[Callable[[float], None]] = None,
        on_reconnected: Optional[Callable[[], None]] = None,
    ) -> None:
        """
        Owns the node's connection to the relay for the lifetime of the
        process (or until `stop_event` is set). On any transient
        failure — network drop, relay restart, DNS hiccup — it closes
        cleanly and retries with exponential backoff + jitter.

        `on_antigen` is called with each antigen payload as it arrives;
        wiring it to LeukocyteAgent.register_antigen(...) (or similar)
        belongs to the caller, same separation of concerns as the rest
        of this module.

        AuthenticationError is NOT retried — a bad token will not fix
        itself by waiting, so this propagates immediately to the
        caller, which should surface it to the operator rather than
        loop silently forever.
        """
        backoff = initial_backoff
        is_reconnect = False  # False for the very first attempt; True for every retry after a drop
        while stop_event is None or not stop_event.is_set():
            try:
                await self.connect()
                if is_reconnect and on_reconnected is not None:
                    on_reconnected()
                is_reconnect = False
                backoff = initial_backoff  # reset only after a real handshake success
                await self._run_session(on_antigen, heartbeat_interval, flush_interval, stop_event)
                # _run_session returns normally only when stop_event fires;
                # any connection loss raises out of it instead.
                if stop_event is not None and stop_event.is_set():
                    break
            except AuthenticationError:
                log.error("relay authentication failed for node_id=%s — not retrying", self.node_id)
                raise
            except (ConnectionError, OSError, websockets.InvalidHandshake, websockets.ConnectionClosed) as e:
                log.warning("relay connection lost: %s", e)
                if on_disconnected is not None:
                    on_disconnected()
                is_reconnect = True
            finally:
                await self.close()

            if stop_event is not None and stop_event.is_set():
                break

            sleep_for = backoff * (1 + random.uniform(-jitter, jitter))
            sleep_for = max(0.0, sleep_for)
            log.info("reconnecting to relay in %.1fs", sleep_for)
            if on_reconnecting is not None:
                on_reconnecting(sleep_for)
            await asyncio.sleep(sleep_for)
            backoff = min(backoff * backoff_factor, max_backoff)

    async def _run_session(
        self,
        on_antigen: Callable[[Dict[str, Any]], Awaitable[None]],
        heartbeat_interval: float,
        flush_interval: float,
        stop_event: Optional[asyncio.Event],
    ) -> None:
        """One connected session: heartbeat + periodic flush running
        alongside the antigen-consuming loop. Returns when the
        connection drops (raises) or stop_event fires (returns)."""
        heartbeat_task = asyncio.create_task(self._safe_background(self.run_heartbeat(heartbeat_interval)))
        flush_task = asyncio.create_task(self._safe_background(self._flush_loop(flush_interval)))
        try:
            async for payload in self.incoming_antigens():
                await on_antigen(payload)
                if stop_event is not None and stop_event.is_set():
                    return
            # incoming_antigens() ended without stop_event being set —
            # the relay closed the connection, possibly cleanly (no
            # ConnectionClosed raised, the async iterator just finished).
            # Treat this the same as a noisy drop: run_forever() must
            # fire on_disconnected() and back off, not silently fall
            # through as if nothing happened.
            raise ConnectionError("relay closed the connection")
        finally:
            heartbeat_task.cancel()
            flush_task.cancel()
            for t in (heartbeat_task, flush_task):
                try:
                    await t
                except asyncio.CancelledError:
                    pass

    @staticmethod
    async def _safe_background(coro: Awaitable[None]) -> None:
        """Background tasks (heartbeat, flush) should never crash the
        session with an unhandled exception if the socket dies mid-send
        — the main incoming_antigens() loop is already the source of
        truth for "connection is dead" and will raise on its own."""
        try:
            await coro
        except websockets.ConnectionClosed:
            pass