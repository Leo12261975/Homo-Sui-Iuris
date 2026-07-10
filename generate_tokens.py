"""
Generates node_tokens.json for bootstrap_relay.py — one cryptographically
random token per tester. Run this ONCE on the server, then distribute
each tester their own token out-of-band (not via the repo, not via a
public channel).

Usage:
    python3 generate_tokens.py Tester_01 Tester_02 Tester_03 ...
"""

import json
import secrets
import sys
from pathlib import Path

OUT_PATH = Path("node_tokens.json")


def main() -> None:
    node_ids = sys.argv[1:]
    if not node_ids:
        print("Usage: python3 generate_tokens.py Tester_01 Tester_02 ...")
        sys.exit(1)

    if OUT_PATH.exists():
        print(f"'{OUT_PATH}' already exists — refusing to overwrite. "
              f"Delete it manually first if you really want to regenerate "
              f"all tokens (this will invalidate every existing tester).")
        sys.exit(1)

    tokens = {node_id: secrets.token_urlsafe(32) for node_id in node_ids}
    OUT_PATH.write_text(json.dumps(tokens, indent=2, ensure_ascii=False), encoding="utf-8")
    OUT_PATH.chmod(0o600)  # readable/writable by the owner only

    print(f"Wrote {len(tokens)} token(s) to {OUT_PATH} (mode 600).")
    print("Distribute each token to its tester individually — do not paste all of them in one shared channel.")
    for node_id, token in tokens.items():
        print(f"  {node_id}: {token}")


if __name__ == "__main__":
    main()