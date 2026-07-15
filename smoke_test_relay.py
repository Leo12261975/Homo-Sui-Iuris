import os
import sys
import asyncio
import websockets
import json

async def main():
    node_id = os.environ.get("HSI_NODE_ID", "Tester_01")
    token = os.environ.get("HSI_NODE_TOKEN")
    
    if not token:
        print("ERROR: Environment variable HSI_NODE_TOKEN is not set.")
        print("Please run: export HSI_NODE_TOKEN='your_token'")
        sys.exit(1)
        
    uri = "wss://relay.w0guard.net"
    print(f"Connecting to {uri} as {node_id}...")
    
    try:
        async with websockets.connect(uri) as websocket:
            auth_packet = {
                "type": "hello",
                "node_id": node_id,
                "token": token
            }
            await websocket.send(json.dumps(auth_packet))
            
            response = await websocket.recv()
            print(f"Relay response: {response}")
            
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
