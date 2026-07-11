"""
Smoke test for bootstrap_relay.py through an SSH tunnel.

Run this on the machine where `ssh -L 8765:localhost:8765 root@93.115.18.18`
is active — it connects to ws://localhost:8765, which the tunnel routes
to the real relay process on the server.

Before running: open node_tokens.json on the server (or the output
generate_tokens.py printed when you created it) and paste one real
token below.
"""

import asyncio
import json
import websockets

NODE_ID = "Tester_01"           # <-- use a real node_id from node_tokens.json
TOKEN = "UdF739Wbwlq-Opa0hDrfGjCFJK_NvvP1v6n0-E8SYAg"  # <-- use the matching token
RELAY_URL = "ws://localhost:8765"


async def main() -> None:
    async with websockets.connect(RELAY_URL) as ws:
        # 1. Handshake
        await ws.send(json.dumps({"type": "hello", "node_id": NODE_ID, "token": TOKEN}))
        ack = json.loads(await ws.recv())
        if ack.get("type") != "hello_ack":
            print(f"FAILED handshake: {ack}")
            return
        print(f"connected as {NODE_ID}, relay ack: {ack}")

        # 2. Send a test antigen
        await ws.send(json.dumps({
            "type": "antigen",
            "payload": {
                "target_weight": "adaptability",
                "distortion_type": "oscillating",
                "signature_hash": "tunnel_smoke_test_signature",
            },
        }))
        print("sent test antigen")

        # 3. Send a test log batch
        await ws.send(json.dumps({
            "type": "log_batch",
            "payload": [{"event": "tunnel_smoke_test", "node_id": NODE_ID}],
        }))
        print("sent test log batch")

        # Give the relay a moment to process and write to disk before closing.
        await asyncio.sleep(0.5)
        print("done — check relay_logs/%s.jsonl on the server, and the left "
              "terminal's relay output, to confirm receipt." % NODE_ID)


if __name__ == "__main__":
    asyncio.run(main())