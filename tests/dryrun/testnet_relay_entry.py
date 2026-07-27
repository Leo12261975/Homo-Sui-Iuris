"""
testnet_relay_entry.py — relay entrypoint for the automated dry run only.

Why this exists instead of running bootstrap_relay.py directly: the production
relay binds 127.0.0.1 by design (see bootstrap_relay.py's docstring — Caddy
terminates TLS and is the only thing that should ever face the internet). Inside
docker-compose.test.yml the relay must be reachable by the *other* containers on
the compose-internal bridge network, so here — and ONLY here — it binds
0.0.0.0.

This is safe in this context, and does not weaken the production model, because:
  - it is a throwaway test network with test-only tokens (node_tokens.test.json),
  - no port is published to the host (see the compose file — the relay has no
    `ports:` mapping), so the socket never leaves the Docker bridge,
  - it never imports into or changes the production default; production still
    runs `python3 bootstrap_relay.py`, which is loopback-only.

All config is env-driven so the compose file is the single source of truth.
"""

from __future__ import annotations

import asyncio
import os

import bootstrap_relay

if __name__ == "__main__":
    host = os.environ.get("HSI_RELAY_HOST", "0.0.0.0")  # test bridge only — never published
    port = int(os.environ.get("HSI_RELAY_PORT", "8765"))
    tokens_file = os.environ.get("HSI_TOKENS_FILE", "node_tokens.test.json")
    log_dir = os.environ.get("HSI_RELAY_LOG_DIR", "relay_logs")

    tokens = bootstrap_relay.load_node_tokens(tokens_file)
    bootstrap_relay.log.info("testnet relay: %d token(s), binding %s:%d", len(tokens), host, port)
    asyncio.run(bootstrap_relay.serve(host=host, port=port, node_tokens=tokens, log_dir=log_dir))
