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
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

import websockets

log = logging.getLogger("node_transport")


class NodeTransport:
    def __init__(self, relay_url: str, node_id: str, token: str) -> None:
        self.relay_url = relay_url
        self.node_id = node_id
        self.token = token
        self._ws: Optional["websockets.WebSocketClientProtocol"] = None
        self._log_buffer: List[Dict[str, Any]] = []

    async def connect(self) -> None:
        self._ws = await websockets.connect(self.relay_url)
        await self._ws.send(json.dumps({
            "type": "hello", "node_id": self.node_id, "token": self.token,
        }))
        ack_raw = await self._ws.recv()
        ack = json.loads(ack_raw)
        if ack.get("type") != "hello_ack":
            raise ConnectionError(f"handshake failed: {ack}")
        log.info("connected to relay as %s", self.node_id)

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()

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
        await self._ws.send(json.dumps({"type": "log_batch", "payload": batch}))

    async def incoming_antigens(self) -> AsyncIterator[Dict[str, Any]]:
        """Yields payload dicts for every antigen relayed from other
        nodes. Runs until the connection drops; caller is responsible
        for reconnect/backoff around this."""
        if self._ws is None:
            raise ConnectionError("not connected")
        async for raw in self._ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "antigen":
                yield msg.get("payload", {})

    async def run_heartbeat(self, interval: float = 30.0) -> None:
        while True:
            await asyncio.sleep(interval)
            if self._ws is not None:
                await self._ws.send(json.dumps({"type": "heartbeat"}))