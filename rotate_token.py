import json
import secrets
import sys

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 rotate_token.py <node_id>")
        sys.exit(1)
        
    node_id = sys.argv[1]
    filename = "node_tokens.json"
    
    try:
        with open(filename, "r") as f:
            tokens = json.load(f)
    except FileNotFoundError:
        tokens = {}
        
    new_token = f"tok_{secrets.token_hex(16)}"
    tokens[node_id] = new_token
    
    with open(filename, "w") as f:
        json.dump(tokens, f, indent=4)
        
    print(f"SUCCESS: Token for {node_id} has been rotated.")
    print(f"NEW TOKEN: {new_token}")

if __name__ == "__main__":
    main()
