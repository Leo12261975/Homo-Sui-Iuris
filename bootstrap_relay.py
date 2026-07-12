import asyncio
import websockets
import json
import os
import sys
from pathlib import Path

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8765
MAX_MESSAGE_BYTES = 1024 * 1024  # 1MB
TOKENS_FILE = "node_tokens.json"
LOG_DIR = "relay_logs"

class Relay:
    def __init__(self, node_tokens: dict, log_dir: str = LOG_DIR):
        self.tokens = node_tokens
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        self.connections = {}  # node_id -> websocket

    async def handle_node(self, websocket):
        node_id = None
        try:
            raw_msg = await websocket.recv()
            msg = json.loads(raw_msg)
            
            if msg.get("type") != "hello":
                await websocket.send(json.dumps({"type": "error", "message": "Expected hello packet"}))
                return
                
            node_id = msg.get("node_id")
            token = msg.get("token")
            
            if node_id in self.tokens and self.tokens[node_id] == token:
                self.connections[node_id] = websocket
                await websocket.send(json.dumps({"type": "hello_ack", "status": "authenticated"}))
                print(f"Node '{node_id}' connected and authenticated successfully.")
            else:
                await websocket.send(json.dumps({"type": "error", "message": "Invalid credentials"}))
                return

            async for message in websocket:
                data = json.loads(message)
                if data.get("type") == "antigen_batch":
                    await self.broadcast_antigen(node_id, data)
                elif data.get("type") == "log_batch":
                    self.save_logs(node_id, data)

        except websockets.exceptions.ConnectionClosed:
            print(f"Node '{node_id}' disconnected.")
        except Exception as e:
            print(f"Error handling node '{node_id}': {e}")
        finally:
            if node_id in self.connections:
                del self.connections[node_id]

    async def broadcast_antigen(self, sender_id, data):
        payload = json.dumps(data)
        for target_id, ws in self.connections.items():
            if target_id != sender_id:
                try:
                    await ws.send(payload)
                except Exception:
                    pass

    def save_logs(self, node_id, data):
        log_file = self.log_dir / f"audit_{node_id}.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(data) + "\n")

def load_tokens():
    if not os.path.exists(TOKENS_FILE):
        print(f"CRITICAL ERROR: {TOKENS_FILE} missing!")
        sys.exit(1)
    with open(TOKENS_FILE, "r") as f:
        return json.load(f)

async def serve(host=DEFAULT_HOST, port=DEFAULT_PORT, node_tokens=None, log_dir=LOG_DIR):
    if node_tokens is None:
        node_tokens = load_tokens()
    relay = Relay(node_tokens, log_dir)
    print(f"Starting FULL-FEATURED bootstrap relay on {host}:{port}...")
    async with websockets.serve(relay.handle_node, host, port, max_size=MAX_MESSAGE_BYTES):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(serve())
