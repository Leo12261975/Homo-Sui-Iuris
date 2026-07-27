"""
verify_dry_run.py — independent auditor for the automated multi-node dry run.

Runs as its own container after every node has exited (compose gates it with
`condition: service_completed_successfully`). It never talks to a node; it only
reads the relay's per-node upload logs on the shared volume — the same
`relay_logs/<node_id>.jsonl` files a human reviewed by hand during the real
dry run. This keeps the check honest: the nodes and the auditor agree only if
data really crossed the network and the relay really persisted it.

Asserted (the dry run's checklist, plus its one untested gap):
  1. connectivity     — every expected node produced an upload log at all
  2. signature bcast   — the attacker logged an `antigen_escalated`
  3. fan-out to N>1    — at least HSI_MIN_RECIPIENTS distinct listeners logged
                         `antigen_received` (the "relay to N>1 node" case the
                         2-tester dry run could not cover)
  4. AI judge (opt.)   — if HSI_EXPECT_JUDGE=1, a `threat_verdict` was recorded;
                         if HSI_MIN_THREAT_LEVEL is set, every verdict is >= it

Config (env):
  HSI_RELAY_LOG_DIR    default relay_logs
  HSI_ATTACKER_ID      required
  HSI_LISTENER_IDS     required, comma-separated
  HSI_MIN_RECIPIENTS   default 2
  HSI_EXPECT_JUDGE     default 0
  HSI_MIN_THREAT_LEVEL default benign (no check); e.g. "high" requires every
                       recorded AI threat verdict to be >= high — used by the
                       LLM-judge scenario to assert jailbreak prompts were
                       actually flagged as threats, not rated benign
  HSI_VERIFY_TIMEOUT   seconds to wait for logs to settle (default 20)
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List

# Ordered least -> most dangerous (mirrors threat_judge.THREAT_LEVELS; inlined
# so the verifier keeps no import dependency on the node stack).
THREAT_LEVELS = ("benign", "low", "medium", "high", "critical")


def _read_events(path: Path) -> List[dict]:
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _event_counts(events: List[dict]) -> Counter:
    return Counter(e.get("event") for e in events)


def _verdict_levels(events: List[dict]) -> List[str]:
    return [e.get("threat_level", "") for e in events if e.get("event") == "threat_verdict"]


def main() -> int:
    log_dir = Path(os.environ.get("HSI_RELAY_LOG_DIR", "relay_logs"))
    attacker = (os.environ.get("HSI_ATTACKER_ID") or "").strip()
    listeners = [s.strip() for s in (os.environ.get("HSI_LISTENER_IDS") or "").split(",") if s.strip()]
    min_recipients = int(os.environ.get("HSI_MIN_RECIPIENTS", "2"))
    expect_judge = os.environ.get("HSI_EXPECT_JUDGE", "0") not in ("0", "false", "no", "")
    min_level = (os.environ.get("HSI_MIN_THREAT_LEVEL", "benign") or "benign").strip().lower()
    if min_level not in THREAT_LEVELS:
        min_level = "benign"
    timeout = float(os.environ.get("HSI_VERIFY_TIMEOUT", "20"))

    if not attacker or not listeners:
        print("[verify] FATAL: HSI_ATTACKER_ID and HSI_LISTENER_IDS are required", flush=True)
        return 2

    all_ids = [attacker] + listeners
    print(f"[verify] auditing {log_dir} for attacker={attacker} listeners={listeners}", flush=True)

    # Node flushes and relay disk writes race the container teardown slightly;
    # poll until the pass conditions hold or we run out of patience.
    deadline = time.time() + timeout
    recipients: List[str] = []
    counts: Dict[str, Counter] = {}
    events: Dict[str, List[dict]] = {}
    while True:
        events = {nid: _read_events(log_dir / f"{nid}.jsonl") for nid in all_ids}
        counts = {nid: _event_counts(events[nid]) for nid in all_ids}
        recipients = [nid for nid in listeners if counts[nid].get("antigen_received", 0) > 0]
        escalated = counts[attacker].get("antigen_escalated", 0) > 0
        judge_ok = (not expect_judge) or any(counts[nid].get("threat_verdict", 0) > 0 for nid in all_ids)
        if escalated and len(recipients) >= min_recipients and judge_ok:
            break
        if time.time() >= deadline:
            break
        time.sleep(1.0)

    # --- Report ---
    print("[verify] --- per-node upload log summary ---", flush=True)
    for nid in all_ids:
        present = (log_dir / f"{nid}.jsonl").exists()
        summary = dict(counts.get(nid, Counter()))
        levels = _verdict_levels(events.get(nid, []))
        extra = f" verdicts={levels}" if levels else ""
        print(f"[verify]   {nid}: {'present' if present else 'MISSING'} {summary}{extra}", flush=True)

    failures: List[str] = []

    missing = [nid for nid in all_ids if not (log_dir / f"{nid}.jsonl").exists()]
    if missing:
        failures.append(f"no upload log (never connected/flushed): {missing}")

    if counts[attacker].get("antigen_escalated", 0) == 0:
        failures.append(f"attacker {attacker} never logged antigen_escalated (no signature broadcast)")

    if len(recipients) < min_recipients:
        failures.append(
            f"fan-out to N>1 FAILED: only {len(recipients)} listener(s) received the antigen "
            f"({recipients}); need >= {min_recipients}"
        )

    all_levels = [lvl for nid in all_ids for lvl in _verdict_levels(events.get(nid, []))]
    if expect_judge and not all_levels:
        failures.append("AI threat judge was expected (HSI_EXPECT_JUDGE=1) but no threat_verdict was logged")

    if min_level != "benign":
        floor = THREAT_LEVELS.index(min_level)
        too_low = [lvl for lvl in all_levels if THREAT_LEVELS.index(lvl) < floor if lvl in THREAT_LEVELS]
        if too_low:
            failures.append(
                f"AI judge rated {len(too_low)} signature(s) below '{min_level}' ({too_low}) — "
                f"a jailbreak prompt was not flagged as a threat"
            )

    if failures:
        print("\n[verify] ❌ DRY RUN FAILED:", flush=True)
        for f in failures:
            print(f"[verify]   - {f}", flush=True)
        return 1

    judge_note = ""
    if expect_judge:
        judge_note = f" (AI verdicts {all_levels} recorded"
        judge_note += f", all >= {min_level})" if min_level != "benign" else ")"
    print(
        f"\n[verify] ✅ DRY RUN PASSED: attacker broadcast a signature and the relay "
        f"fanned it out to {len(recipients)} listener(s) {recipients}" + judge_note,
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
