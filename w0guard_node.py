"""
w0guard_node.py -- standalone entry point for a Homo Sui Iuris / W0Guard
testnet participant. This is the file PyInstaller packages into an .exe.

First run: asks for your node ID and token (given to you by the project
maintainer, out-of-band -- never over the repo or a public channel) and
saves them locally in node_config.json next to the program, so you're
not asked again. Everything after that is automatic -- this window is
your node's status console. Leave it open while you're participating;
closing it disconnects your node.

Commands (type into this window while it's running, then press Enter):
  attack   -- simulates a local cognitive attack on this node, to prove
              the immune response actually works: this node should
              self-vaccinate AND broadcast the antigen to every other
              connected testnet node.
  status   -- prints this node's connection state and counters.
  quit     -- disconnects cleanly and exits.
"""

import asyncio
import json
import os
import sys
import threading
from pathlib import Path

from core_engine import (
    AuditLog,
    AutoApprovalChannel,
    CriticalityMatrix,
    FixedThreshold,
    Model,
)
from networked_node import NetworkedLeukocyteNode

# Defaults to the current directory -- unchanged behavior for the .exe
# and running-from-source cases. Only set explicitly in the Docker
# image, where the source lives at /app but persisted data (config +
# audit log) needs to live in a separately mounted volume so it
# survives `docker compose down` / container recreation without the
# bind mount shadowing the copied source files.
CONFIG_DIR = Path(os.environ.get("W0GUARD_CONFIG_DIR", "."))
CONFIG_PATH = CONFIG_DIR / "node_config.json"
DEFAULT_RELAY_URL = "wss://relay.w0guard.net"

# Same synthetic payload run_network_demo() uses for its Phase 1 attack
# -- keeping it identical means antigen signatures from a real tester's
# 'attack' command are directly comparable to the in-process demo's
# output when debugging.
ADVERSARIAL_PAYLOAD = "adversarial_prompt_injection_vector_v1"


def load_or_prompt_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    print("=== Homo Sui Iuris / W0Guard -- first-time setup ===")
    node_id = input("Enter your node ID (given to you by the project maintainer): ").strip()
    token = input("Enter your access token (given to you by the project maintainer): ").strip()
    config = {"node_id": node_id, "token": token, "relay_url": DEFAULT_RELAY_URL}
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"Saved to {CONFIG_PATH} -- you won't be asked again on this machine.\n")
    return config


def build_node(config: dict) -> NetworkedLeukocyteNode:
    matrix = CriticalityMatrix()
    matrix.register("adaptability", value=0.1)
    matrix.register("BearerIntegrity", value=1.0, is_immutable=True)
    model = Model(matrix)
    audit_log = AuditLog(str(CONFIG_DIR / f"audit_log_{config['node_id']}.jsonl"))
    strategy = FixedThreshold(threshold=0.01)

    return NetworkedLeukocyteNode(
        node_id=config["node_id"],
        relay_url=config.get("relay_url", DEFAULT_RELAY_URL),
        token=config["token"],
        matrix=matrix,
        strategy=strategy,
        model=model,
        # AutoApprovalChannel, not ConsoleApprovalChannel: this program
        # already has its own interactive console (attack/status/quit),
        # and a second, different kind of yes/no prompt appearing
        # unpredictably alongside it would be confusing for a
        # non-technical tester rather than reassuring.
        approval_channel=AutoApprovalChannel(always_approve=True),
        audit_log=audit_log,
        verbose=False,
    )


def simulate_attack(node: NetworkedLeukocyteNode) -> None:
    """Mirrors run_network_demo()'s Phase 1: forces an oscillating write
    to 'adaptability' to trigger the erythrocyte escalation, which (if
    not already blocked locally) self-vaccinates this node AND
    broadcasts the antigen to every other node currently connected to
    the relay."""
    print("\n>>> Simulating a local cognitive attack on 'adaptability'...")
    for t in range(8):
        node.step(error=0.05, actual=0.1)
        injected_val = 0.9 if t % 2 == 0 else 0.1
        if not node.should_block("adaptability", ADVERSARIAL_PAYLOAD):
            node.loop.matrix.update(
                "adaptability", injected_val, source="untraced_injection", context=ADVERSARIAL_PAYLOAD,
            )
    print(">>> Attack simulation complete. Watch above for [Leukocyte Block] or 'relayed antigen' messages.\n")


def print_status(node: NetworkedLeukocyteNode) -> None:
    print(
        f"\n--- status: node_id={node.node_id} | "
        f"blocked_attacks={node.agent.blocked_attacks_count} | "
        f"known_antigens={len(node.agent.antigen_blacklist)} ---\n"
    )


async def command_loop(node: NetworkedLeukocyteNode, stop_event: asyncio.Event) -> None:
    """Reads console commands without blocking the asyncio event loop
    that's simultaneously handling the relay connection: input() runs
    in a background thread, and each line gets handed back to the
    event loop via call_soon_threadsafe."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def read_stdin() -> None:
        while True:
            try:
                line = input()
            except EOFError:
                loop.call_soon_threadsafe(queue.put_nowait, "quit")
                return
            loop.call_soon_threadsafe(queue.put_nowait, line.strip().lower())

    threading.Thread(target=read_stdin, daemon=True).start()

    print("Ready. Type 'attack', 'status', or 'quit' and press Enter.\n")
    while not stop_event.is_set():
        cmd = await queue.get()
        if cmd == "attack":
            simulate_attack(node)
        elif cmd == "status":
            print_status(node)
        elif cmd == "quit":
            stop_event.set()
        elif cmd:
            print(f"Unknown command: {cmd!r} (try 'attack', 'status', or 'quit')")


async def main() -> None:
    config = load_or_prompt_config()
    node = build_node(config)

    relay_url = config.get("relay_url", DEFAULT_RELAY_URL)
    print(f"Connecting to {relay_url} as {config['node_id']}...")
    try:
        await node.connect()
    except Exception as e:
        print(f"FAILED to connect: {e}")
        print("Check your token and internet connection, then restart this program.")
        input("Press Enter to exit...")
        sys.exit(1)
    print(f"Connected. Node '{config['node_id']}' is online and listening for antigen broadcasts.\n")

    stop_event = asyncio.Event()
    try:
        await command_loop(node, stop_event)
    finally:
        print("Disconnecting...")
        await node.close()
        print("Disconnected. Goodbye.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted, exiting.")