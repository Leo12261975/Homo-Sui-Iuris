"""
testnet_node_driver.py — headless, non-interactive W0Guard node for the
automated multi-node dry run (docker-compose.test.yml).

The shipped client (w0guard_node.py) reads commands from a TTY, which can't be
driven unattended. This driver is the same NetworkedLeukocyteNode wired to run
a *scripted* dry-run role instead of a console, so N nodes can be brought up as
separate containers and asserted on with no human in the loop. It reproduces
the DRY_RUN_2026_07_18 scenario and closes its documented gap: relay fan-out to
more than one recipient at once.

Everything is configured by environment variable (12-factor, container-native):

  HSI_NODE_ID       (required)  this node's id, must match node_tokens.test.json
  HSI_NODE_TOKEN    (required)  its token
  HSI_RELAY_URL     (required)  e.g. ws://relay:8765
  HSI_ROLE          attacker | listener   (default: listener)
  HSI_ATTACK_DELAY  seconds an attacker waits for peers to connect (default 8)
  HSI_RUN_SECONDS   total lifetime before a clean quit (default 25)
  HSI_CONNECT_TIMEOUT  first-handshake timeout (default 15)
  HSI_EXPECT_ANTIGEN   listener exits non-zero if it received none (default 1)
  plus the HSI_THREAT_JUDGE / HSI_JUDGE_* vars consumed by threat_judge.py

Exit code is the node's own verdict on its role (attacker attacked and
self-vaccinated; listener received an antigen). The separate verifier container
cross-checks the whole network from the relay's logs — the two are independent
on purpose.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from core_engine import (
    AuditLog,
    AutoApprovalChannel,
    CriticalityMatrix,
    FixedThreshold,
    Model,
)
from networked_node import NetworkedLeukocyteNode
from threat_judge import build_threat_judge_from_env
from w0guard_node import ADVERSARIAL_PAYLOAD

CONFIG_DIR = Path(os.environ.get("W0GUARD_CONFIG_DIR", "."))


def parse_payloads() -> list[str]:
    """Attack payloads (the raw prompts injected as attack context). Multiple
    distinct ones — separated by '||' in HSI_ATTACK_PAYLOADS — each become their
    own antigen with its own threat verdict, which is how the LLM-judge scenario
    feeds several realistic jailbreak prompts through one attack."""
    raw = os.environ.get("HSI_ATTACK_PAYLOADS", "").strip()
    if not raw:
        return [ADVERSARIAL_PAYLOAD]
    return [p.strip() for p in raw.split("||") if p.strip()] or [ADVERSARIAL_PAYLOAD]


def run_attack(node: NetworkedLeukocyteNode, payloads: list[str]) -> None:
    """Same oscillating attack as w0guard_node.simulate_attack, but cycling
    through several payloads so one escalation fingerprints each distinct
    prompt (erythrocyte.collect_observed_contexts returns the distinct set)."""
    print(f"\n>>> Simulating a local cognitive attack on 'adaptability' with {len(payloads)} payload(s)...", flush=True)
    for t in range(8):
        node.step(error=0.05, actual=0.1)
        injected_val = 0.9 if t % 2 == 0 else 0.1
        payload = payloads[t % len(payloads)]
        if not node.should_block("adaptability", payload):
            node.loop.matrix.update("adaptability", injected_val, source="untraced_injection", context=payload)
    print(">>> Attack simulation complete.\n", flush=True)


def _env(name: str, default: str | None = None, required: bool = False) -> str:
    val = os.environ.get(name, default)
    if required and not val:
        print(f"[driver] FATAL: environment variable {name} is required", flush=True)
        sys.exit(2)
    return val  # type: ignore[return-value]


def build_node(node_id: str, token: str, relay_url: str) -> NetworkedLeukocyteNode:
    matrix = CriticalityMatrix()
    matrix.register("adaptability", value=0.1)
    matrix.register("BearerIntegrity", value=1.0, is_immutable=True)
    model = Model(matrix)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    audit_log = AuditLog(str(CONFIG_DIR / f"audit_log_{node_id}.jsonl"))
    strategy = FixedThreshold(threshold=0.01)
    judge = build_threat_judge_from_env()
    if judge is not None:
        print(f"[driver] threat judge enabled: {type(judge).__name__}", flush=True)

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
        # Fast, deterministic timers for a short test run (defaults are tuned
        # for a long-lived human session).
        log_flush_interval=2.0,
        heartbeat_interval=5.0,
        connect_timeout=float(_env("HSI_CONNECT_TIMEOUT", "15")),
        threat_judge=judge,
        # Bounded wait on close() for slow AI verdicts to finish + flush.
        judge_drain_timeout=float(_env("HSI_JUDGE_DRAIN_TIMEOUT", "90")),
        on_disconnected=lambda: print(f"[{node_id}] ⚠ disconnected — reconnecting...", flush=True),
        on_reconnecting=lambda s: print(f"[{node_id}] reconnecting in {s:.1f}s", flush=True),
        on_reconnected=lambda: print(f"[{node_id}] ✅ reconnected", flush=True),
    )


async def run() -> int:
    node_id = _env("HSI_NODE_ID", required=True)
    token = _env("HSI_NODE_TOKEN", required=True)
    relay_url = _env("HSI_RELAY_URL", required=True)
    role = _env("HSI_ROLE", "listener").strip().lower()
    attack_delay = float(_env("HSI_ATTACK_DELAY", "8"))
    run_seconds = float(_env("HSI_RUN_SECONDS", "25"))
    expect_antigen = _env("HSI_EXPECT_ANTIGEN", "1") not in ("0", "false", "no", "")
    # Soft self-checks (did I self-vaccinate / receive?) affect the exit code
    # only when strict. Under compose we set HSI_STRICT=0 so a soft miss still
    # exits 0 — otherwise `depends_on: service_completed_successfully` would
    # block the verifier, which is meant to be the one authoritative judge.
    # A real crash / connect failure still exits non-zero regardless.
    strict = _env("HSI_STRICT", "1") not in ("0", "false", "no", "")

    node = build_node(node_id, token, relay_url)
    print(f"[{node_id}] role={role} connecting to {relay_url} ...", flush=True)
    try:
        await node.connect()
    except Exception as e:  # bad token, relay down, etc.
        print(f"[{node_id}] FAILED to connect: {e}", flush=True)
        return 1
    print(f"[{node_id}] online.", flush=True)

    deadline = asyncio.get_event_loop().time() + run_seconds
    exit_code = 0
    try:
        if role == "attacker":
            # Give listeners time to establish their relay connections — the
            # broadcast fires once and has no retry to late joiners.
            print(f"[{node_id}] waiting {attack_delay:.0f}s for peers to connect...", flush=True)
            await asyncio.sleep(attack_delay)
            run_attack(node, parse_payloads())
            # Let the fire-and-forget broadcast + any (possibly slow) judge
            # tasks run before we start counting down the window.
            await asyncio.sleep(1.0)
            if not node.agent.antigen_blacklist:
                print(f"[{node_id}] ERROR: attack did not self-vaccinate", flush=True)
                if strict:
                    exit_code = 1
            else:
                print(f"[{node_id}] self-vaccinated ({len(node.agent.antigen_blacklist)} antigen(s))", flush=True)

        # Stay online for the rest of the window (attacker keeps serving the
        # broadcast; listeners keep receiving).
        remaining = max(0.0, deadline - asyncio.get_event_loop().time())
        await asyncio.sleep(remaining)

        known = len(node.agent.antigen_blacklist)
        print(
            f"[{node_id}] window closed | known_antigens={known} "
            f"blocked_attacks={node.agent.blocked_attacks_count}",
            flush=True,
        )
        if role == "listener" and expect_antigen and known == 0:
            print(f"[{node_id}] ERROR: listener received no antigen over the network", flush=True)
            if strict:
                exit_code = 1
    finally:
        await node.close()  # flushes remaining logs to the relay, then disconnects
        print(f"[{node_id}] disconnected cleanly.", flush=True)

    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(run()))
    except KeyboardInterrupt:
        sys.exit(130)
