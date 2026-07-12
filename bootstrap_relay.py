"""
Homo Sui Iuris / Free Cognitive Protocol — External testnet bootstrap relay.

Role: replaces the in-process P2PNetworkSimulation.broadcast_antigen()
(leukocyte_protocol.py) with a real network hop, for a testnet of
volunteer nodes spread across the real internet.

Topology decision (deliberate, not the naive reading of "TCP/IP P2P"):
this is a hub-and-relay design, not a true peer mesh. Volunteer testers
are behind home NAT with no port forwarding, so inbound connections to
their machines will not work. Every node makes ONE outbound connection
to this relay; the relay fans antigen broadcasts back out to everyone
else. The Leukocyte/Erythrocyte detection and blocking logic itself
stays entirely local to each node — only the transport for
broadcast_antigen() changes.

Deployment topology (relay.w0guard.net):
  internet --443/TLS--> Caddy (reverse proxy, cert via Let's Encrypt)
      --127.0.0.1:8765/plain ws--> this process

  This process itself NEVER speaks TLS and NEVER listens on a
  publicly-routable interface. It binds 127.0.0.1 only — Caddy is the
  only thing standing between it and the open internet. This is a
  deliberate separation of concerns: TLS cert issuance/renewal is
  Caddy's job (it does this automatically), so this file has zero
  certificate-handling code to get wrong. See /etc/caddy/Caddyfile in
  the ops docs for the proxy config.

  Do NOT change `host` back to "0.0.0.0" without also reconsidering
  this whole security model — that would make the relay directly
  reachable from the internet, bypassing Caddy (and TLS) entirely,
  even if Caddy is still separately configured. ufw should also have
  no rule opening 8765 externally; loopback-only binding plus a closed
  port is defense in depth, not either/or.

Security notes (apply regardless of "friendly testnet" framing, because
this process will be reachable from the real internet, via Caddy):
  - Only json.loads() is ever used on network input. Never pickle/eval
    on anything that arrived over the wire.
  - node_id used to build a log file path comes ONLY from the
    authenticated handshake (checked against NODE_TOKENS), never taken
    raw from a later message — this closes an obvious path-traversal /
    arbitrary-file-write vector.
  - Message size is capped (MAX_MESSAGE_BYTES) to avoid one node
    exhausting server memory.
  - Auth tokens now travel over wss:// (TLS terminated by Caddy) end to
    end from the client's perspective — the plain-ws hop only exists on
    loopback, which never leaves the machine.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Dict, Optional

import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("relay")

# Pre-registered testnet participants. Loaded at runtime from a local
# JSON file (see load_node_tokens below) — never hardcoded here, and
# that file must never be committed to the repository (add it to
# .gitignore). This module-level dict exists only as the default for
# tests that construct Relay/serve() directly with their own
# node_tokens argument.
NODE_TOKENS: Dict[str, str] = {}

DEFAULT_HOST = "127.0.0.1"  # loopback only — see module docstring
DEFAULT_LOG_DIR = "relay_logs"
DEFAULT_TOKENS_FILE = "node_tokens.json"
MAX_MESSAGE_BYTES = 64 * 1024
HANDSHAKE_TIMEOUT_SECONDS = 10


def load_node_tokens(path: str = DEFAULT_TOKENS_FILE) -> Dict[str, str]:
    """
    Loads {node_id: token} from a local JSON file. This file is
    operational secret material, not source code — it must be created
    directly on the server (or copied out-of-band), never committed.

    Fails loudly rather than silently falling back to an empty dict:
    an empty NODE_TOKENS means the relay starts up and rejects every
    single connection, which is a confusing way to discover the file
    was missing or malformed.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Token file '{path}' not found. Create it on the server "
            f"(never commit it) as a JSON object, e.g.:\n"
            f'  {{"Tester_01": "a-long-random-token", "Tester_02": "..."}}\n'
            f"See generate_tokens.py for a script that creates one with "
            f"cryptographically random tokens."
        )
    with p.open("r", encoding="utf-8") as f:
        tokens = json.load(f)
    if not isinstance(tokens, dict) or not tokens:
        raise ValueError(f"Token file '{path}' must contain a non-empty JSON object of {{node_id: token}}.")
    return tokens


class Relay:
    def __init__(self, node_tokens: Dict[str, str], log_dir: str = DEFAULT_LOG_DIR) -> None:
        self.node_tokens = node_tokens
        self.connections: Dict[str, "websockets.WebSocketServerProtocol"] = {}
        # Resolved and created here, at instantiation time, not at
        # module-import time -- otherwise the directory ends up wherever
        # the process happened to be when bootstrap_relay.py was first
        # imported, which is surprising and hard to override per-run.
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)

    async def handle(self, ws) -> None:
        node_id: Optional[str] = None
        try:
            node_id = await self._authenticate(ws)
            if node_id is None:
                return
            self.connections[node_id] = ws
            log.info("node connected: %s (%d online)", node_id, len(self.connections))
            async for raw in ws:
                await self._dispatch(node_id, raw)
        except websockets.ConnectionClosed:
            pass
        finally:
            if node_id and self.connections.get(node_id) is ws:
                del self.connections[node_id]
                log.info("node disconnected: %s (%d online)", node_id, len(self.connections))

    async def _authenticate(self, ws) -> Optional[str]:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=HANDSHAKE_TIMEOUT_SECONDS)
        except (asyncio.TimeoutError, websockets.ConnectionClosed):
            return None
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            await ws.close(code=4000, reason="invalid json")
            return None
        if msg.get("type") != "hello":
            await ws.close(code=4001, reason="expected hello")
            return None
        node_id = msg.get("node_id")
        token = msg.get("token")
        if not isinstance(node_id, str) or self.node_tokens.get(node_id) != token:
            await ws.close(code=4003, reason="auth failed")
            log.warning("auth failed for node_id=%r", node_id)
            return None
        await ws.send(json.dumps({"type": "hello_ack", "node_id": node_id}))
        return node_id

    async def _dispatch(self, sender_id: str, raw: str) -> None:
        if len(raw) > MAX_MESSAGE_BYTES:
            log.warning("oversized message from %s dropped", sender_id)
            return
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("malformed json from %s dropped", sender_id)
            return

        msg_type = msg.get("type")
        if msg_type == "antigen":
            await self._relay_antigen(sender_id, msg)
        elif msg_type == "log_batch":
            self._write_log_batch(sender_id, msg)
        elif msg_type == "heartbeat":
            pass
        else:
            log.warning("unknown message type %r from %s", msg_type, sender_id)

    async def _relay_antigen(self, sender_id: str, msg: dict) -> None:
        payload = msg.get("payload", {})
        envelope = json.dumps({"type": "antigen", "sender_id": sender_id, "payload": payload})
        targets = [nid for nid in self.connections if nid != sender_id]
        for nid in targets:
            try:
                await self.connections[nid].send(envelope)
            except websockets.ConnectionClosed:
                continue
        log.info(
            "relayed antigen from %s to %d node(s) (target_weight=%s)",
            sender_id, len(targets), payload.get("target_weight"),
        )

    def _write_log_batch(self, sender_id: str, msg: dict) -> None:
        entries = msg.get("payload", [])
        if not isinstance(entries, list):
            log.warning("log_batch payload from %s was not a list, dropped", sender_id)
            return
        # sender_id is the authenticated node_id from the handshake, not
        # taken from this message — always one of NODE_TOKENS' keys, so
        # it is safe to use directly in a filename.
        path = self.log_dir / f"{sender_id}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        log.info("wrote %d log entries for %s", len(entries), sender_id)


async def serve(
    host: str = DEFAULT_HOST,
    port: int = 8765,
    node_tokens: Optional[Dict[str, str]] = None,
    log_dir: str = DEFAULT_LOG_DIR,
):
    relay = Relay(node_tokens if node_tokens is not None else NODE_TOKENS, log_dir=log_dir)
    async with websockets.serve(relay.handle, host, port, max_size=MAX_MESSAGE_BYTES):
        log.info("relay listening on %s:%d (expects Caddy in front for TLS)", host, port)
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        tokens = load_node_tokens()
    except (FileNotFoundError, ValueError) as e:
        log.error(str(e))
        sys.exit(1)
    log.info("loaded %d registered node token(s)", len(tokens))
    # host defaults to 127.0.0.1 (DEFAULT_HOST) — Caddy is the only
    # process that should ever see a connection from the outside.
    asyncio.run(serve(node_tokens=tokens))
