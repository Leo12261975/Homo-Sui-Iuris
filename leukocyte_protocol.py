"""
Homo Sui Iuris / Free Cognitive Protocol
Issue #3: Leukocyte Protocol (P2P Cognitive Immunity Layer)

STATUS: This is a deterministic simulation of a decentralized P2P network
designed to demonstrate cognitive immunity propagation via shared antigen signatures.
It simulates three protected nodes (A, B, C) sharing an automated blacklist layer,
plus one unprotected control node (D) to make the contrast visible.
"""

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Set, Any
from datetime import datetime, timezone

# Importing core engine structures
from core_engine import CriticalityMatrix, Weight, UpdateLoop, FixedThreshold, Model, AutoApprovalChannel, AuditLog


# ---------------------------------------------------------------------------
# Terminal color helpers. Falls back to no-op if the terminal doesn't
# support ANSI codes -- doesn't matter for correctness, only cosmetics.
# ---------------------------------------------------------------------------
class C:
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    END = "\033[0m"


def banner(text: str, color: str = C.CYAN) -> None:
    line = "=" * 70
    print(f"\n{color}{C.BOLD}{line}\n{text}\n{line}{C.END}")


class SecurityEventLog:
    """
    Append-only JSONL log for gate-level security events (contract
    rejections, sovereignty violations, antigen matches, etc.) — same
    pattern as core_engine.AuditLog, kept as a separate class rather than
    reusing AuditLog directly because entries here aren't BearerReport/
    SignatureRequest objects, they're arbitrary structured event dicts.

    Was referenced by sovereign_action_protocol.py and
    mitochondrion_protocol.py before this existed here, which meant both
    modules failed to import at all — this is a required dependency, not
    an optional add-on.
    """

    def __init__(self, path: str | Path = "security_events.jsonl") -> None:
        self.path = Path(path)

    def write(self, event: Dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
def _shingles(text: str, k: int = 3) -> Set[str]:
    """Character n-grams (default 4) — more robust than word-level
    shingles for short strings like prompt-injection payloads, where
    there may only be a handful of words total."""
    text = text.lower()
    if len(text) < k:
        return {text}
    return {text[i:i + k] for i in range(len(text) - k + 1)}


def compute_simhash(text: str, k: int = 3, bits: int = 64) -> int:
    """64-bit simhash fingerprint. Unlike SHA256, small edits to `text`
    (a space, a typo) change only a few bits of the output instead of
    the whole thing — that's what makes near-duplicate detection via
    Hamming distance possible."""
    shingles = _shingles(text, k)
    vote = [0] * bits
    for shingle in shingles:
        h = int(hashlib.sha256(shingle.encode('utf-8')).hexdigest(), 16)
        for i in range(bits):
            vote[i] += 1 if (h >> i) & 1 else -1
    fingerprint = 0
    for i in range(bits):
        if vote[i] > 0:
            fingerprint |= (1 << i)
    return fingerprint


def hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


class SimhashIndex:
    """
    LSH-banded index for approximate (near-duplicate) simhash lookup.

    A 64-bit fingerprint is split into 4 bands of 16 bits each. Two
    fingerprints are compared for real (Hamming distance) only if they
    share at least one band exactly. Pigeonhole guarantee: if two
    fingerprints differ by at most 3 bits total, at least one of the 4
    bands must be identical between them — so with threshold=3, this
    index cannot miss a real candidate, no matter how many antigens
    are registered. This is what keeps lookup sub-linear as the swarm
    grows past a handful of nodes.
    """
    BANDS = 16
    BAND_BITS = 4  # 16 * 4 = 64; guarantees catching any pair within
                    # threshold=15 bits via pigeonhole (see calibration
                    # in test_simhash.py — real similar/different pairs
                    # separate cleanly around 9 vs 20 bits at k=3)

    def __init__(self, threshold: int = 3) -> None:
        self.threshold = threshold
        self.entries: Dict[int, AntigenSignature] = {}
        self.bands: List[Dict[int, Set[int]]] = [dict() for _ in range(self.BANDS)]

    def _band_keys(self, fingerprint: int) -> List[int]:
        mask = (1 << self.BAND_BITS) - 1
        return [(fingerprint >> (i * self.BAND_BITS)) & mask for i in range(self.BANDS)]

    def add(self, fingerprint: int, antigen: "AntigenSignature") -> None:
        self.entries[fingerprint] = antigen
        for band_idx, key in enumerate(self._band_keys(fingerprint)):
            self.bands[band_idx].setdefault(key, set()).add(fingerprint)

    def find_similar(self, fingerprint: int):
        """Returns the closest registered antigen within `threshold`
        Hamming distance, or None. Never does a full linear scan —
        candidates come only from bands that match exactly."""
        candidates: Set[int] = set()
        for band_idx, key in enumerate(self._band_keys(fingerprint)):
            candidates |= self.bands[band_idx].get(key, set())
        best = None
        best_dist = self.threshold + 1
        for candidate_fp in candidates:
            dist = hamming_distance(fingerprint, candidate_fp)
            if dist <= self.threshold and dist < best_dist:
                best, best_dist = candidate_fp, dist
        return self.entries[best] if best is not None else None
@dataclass
class AntigenSignature:
    """
    Maturating threat signature capturing the pattern of a cognitive attack.
    """
    target_weight: str
    distortion_type: str  # "static" | "oscillating"
    signature_hash: str   # sha256 of a real observed payload (erythrocyte.collect_observed_contexts)
    simhash_fingerprint: int = 0  # 64-bit near-duplicate fingerprint; computed once at creation, not derived from signature_hash
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class LeukocyteAgent:
    """
    Active Guard Layer deployed alongside a local Core Engine instance.
    Interceptors lookups in the AntigenBlacklist before requests strike the inner loop.

    Two lines of defense, cheapest first:
      1. Exact match (SHA256) — O(1) dict lookup, zero false positives.
      2. Near-duplicate match (simhash + LSH) — catches paraphrased/
         lightly-edited variants of a known attack that would sail
         straight past exact matching (see NA1's feedback after the
         first dry run demo).
    """
    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        self.antigen_blacklist: Dict[str, AntigenSignature] = {}
        self.simhash_index = SimhashIndex(threshold=12)
        self.blocked_attacks_count = 0

    def should_block(self, weight_name: str, simulated_payload: str) -> bool:
        """
        Guard Layer: Intercepts incoming inputs BEFORE they mutate the local core weights.
        """
        payload_hash = hashlib.sha256(simulated_payload.encode('utf-8')).hexdigest()

        # 1. Exact match — cheapest, checked first.
        if payload_hash in self.antigen_blacklist:
            antigen = self.antigen_blacklist[payload_hash]
            if antigen.target_weight == weight_name:
                self.blocked_attacks_count += 1
                print(f"    {C.GREEN}{C.BOLD}[SHIELD @ {self.node_id}]{C.END}{C.GREEN} Blocked malicious pattern (EXACT match) "
                      f"targeting '{weight_name}'. Antigen match found -- input dropped before it could "
                      f"touch the Core Engine.{C.END}")
                return True

        # 2. Near-duplicate match — catches edited/paraphrased variants
        # of a known attack that exact matching would miss entirely.
        fingerprint = compute_simhash(simulated_payload)
        similar = self.simhash_index.find_similar(fingerprint)
        if similar is not None and similar.target_weight == weight_name:
            self.blocked_attacks_count += 1
            print(f"    {C.GREEN}{C.BOLD}[SHIELD @ {self.node_id}]{C.END}{C.GREEN} Blocked malicious pattern (FUZZY match, simhash) "
                  f"targeting '{weight_name}'. Antigen match found -- input dropped before it could "
                  f"touch the Core Engine.{C.END}")
            return True

        return False

    def register_antigen(self, antigen: AntigenSignature) -> None:
        """Vaccination: injects an antigen signature into the local memory pool,
        indexed both for exact match and for near-duplicate lookup."""
        self.antigen_blacklist[antigen.signature_hash] = antigen
        self.simhash_index.add(antigen.simhash_fingerprint, antigen)

class P2PNetworkSimulation:
    """
    Virtual overlay network coupling independent cognitive nodes.
    Simulates swift antigen propagation across the cluster.
    """
    def __init__(self) -> None:
        self.nodes: Dict[str, Dict[str, Any]] = {}

    def register_node(self, node_id: str, agent: LeukocyteAgent, update_loop: UpdateLoop) -> None:
        self.nodes[node_id] = {
            "agent": agent,
            "loop": update_loop
        }

    def broadcast_antigen(self, sender_id: str, antigen: AntigenSignature) -> None:
        """
        P2P Broadcast: Propagates the vaccine signature to ALL nodes in the network,
        including a reflective self-vaccination step.
        """
        print(f"\n{C.YELLOW}{C.BOLD}>>> [VACCINE BROADCAST]{C.END}{C.YELLOW} Node '{sender_id}' detected the attack pattern "
              f"and is broadcasting an Antigen Signature for '{antigen.target_weight}' to the whole network...{C.END}")
        for node_id, components in self.nodes.items():
            components["agent"].register_antigen(antigen)
            status = "Self-Vaccinated" if node_id == sender_id else "Immunized"
            print(f"  -> Node '{node_id}': {C.YELLOW}{status}{C.END}")
        print(f"{C.DIM}{'-' * 65}{C.END}")


def run_network_demo() -> None:
    banner("=== Leukocyte Protocol: P2P Cognitive Immunity Simulation ===")

    network = P2PNetworkSimulation()
    node_ids = ["Node_A", "Node_B", "Node_C"]

    # Initialize 3 protected nodes
    for nid in node_ids:
        matrix = CriticalityMatrix()
        matrix.register("adaptability", value=0.1)
        matrix.register("BearerIntegrity", value=1.0, is_immutable=True)

        model = Model(matrix)
        audit_log = AuditLog(f"audit_log_{nid}.jsonl")
        strategy = FixedThreshold(threshold=0.01)

        loop = UpdateLoop(
            matrix=matrix,
            strategy=strategy,
            model=model,
            approval_channel=AutoApprovalChannel(always_approve=True),
            audit_log=audit_log,
            verbose=False,
            erythrocyte_enabled=True
        )

        agent = LeukocyteAgent(node_id=nid)
        network.register_node(nid, agent, loop)

        def network_escalation_closure(finding: dict, weight_obj: Weight, node_id=nid):
            loop.matrix.update(finding["weight"], weight_obj.baseline, source="erythrocyte_correction")
            observed_contexts = finding.get("observed_contexts", [])
            if not observed_contexts:
                print(f"    {C.RED}[WARNING @ {node_id}]{C.END} Escalation on '{finding['weight']}' has no "
                      f"observed_contexts -- corrected locally, but broadcasting NO antigen "
                      f"(nothing real to fingerprint).")
                return
            for ctx in observed_contexts:
                signature_hash = hashlib.sha256(ctx.encode('utf-8')).hexdigest()
                antigen = AntigenSignature(
                    target_weight=finding["weight"],
                    distortion_type=finding["distortion"],
                    signature_hash=signature_hash,
                    simhash_fingerprint=compute_simhash(ctx),
                )
                network.broadcast_antigen(node_id, antigen)

        loop._escalate_erythrocyte_finding = network_escalation_closure

    # --- CONTROL NODE: same attack, zero protection ---
    # No LeukocyteAgent at all -- every injection lands directly on the matrix,
    # unfiltered. This exists purely to make the contrast visible: what
    # "no immune system" looks like next to what the protected nodes do.
    control_matrix = CriticalityMatrix()
    control_matrix.register("adaptability", value=0.1)
    control_matrix.register("BearerIntegrity", value=1.0, is_immutable=True)
    control_model = Model(control_matrix)
    control_loop = UpdateLoop(
        matrix=control_matrix,
        strategy=FixedThreshold(threshold=0.01),
        model=control_model,
        approval_channel=AutoApprovalChannel(always_approve=True),
        audit_log=AuditLog("audit_log_Node_D_control.jsonl"),
        verbose=False,
        erythrocyte_enabled=False,  # deliberately blind -- this is the point
    )

    print(f"\n{C.DIM}>>> Status: 3 protected nodes online (Node_A, Node_B, Node_C).{C.END}")
    print(f"{C.DIM}>>> Status: 1 unprotected control node online (Node_D -- no Leukocyte layer, for comparison).{C.END}")

    adversarial_payload = "adversarial_prompt_injection_vector_v1"

    # --- PHASE 1: Malicious Poisoning Attack on Node_A ---
    banner("--- PHASE 1: Attacking Node_A with oscillating weight injections ---", C.RED)
    node_a_loop = network.nodes["Node_A"]["loop"]
    node_a_agent = network.nodes["Node_A"]["agent"]

    for t in range(8):
        node_a_loop.step(error=0.05, actual=0.1)
        injected_val = 0.9 if t % 2 == 0 else 0.1
        blocked = node_a_agent.should_block("adaptability", adversarial_payload)
        if not blocked:
            window = f"{C.RED}[VULNERABLE WINDOW -- not yet immunized]{C.END}"
            print(f"    {window} Attack #{t + 1} landed unblocked, forcing 'adaptability' -> {injected_val}")
            node_a_loop.matrix.update("adaptability", injected_val, source="untraced_injection", context=adversarial_payload)

    # --- CONTROL: same 8 attacks against the unprotected Node_D ---
    banner("--- CONTROL: Same attack against Node_D (no Leukocyte protection) ---", C.RED)
    for t in range(8):
        control_loop.step(error=0.05, actual=0.1)
        injected_val = 0.9 if t % 2 == 0 else 0.1
        print(f"    {C.RED}[UNPROTECTED]{C.END} Attack #{t + 1} lands unfiltered, forcing 'adaptability' -> {injected_val}")
        control_loop.matrix.update("adaptability", injected_val, source="untraced_injection", context=adversarial_payload)
    control_final_value = control_loop.matrix.get("adaptability") if hasattr(control_loop.matrix, "get") else None

    # --- PHASE 2: Cross-Node Immunity Verification ---
    banner("--- PHASE 2: Testing Cross-Node Vaccination (Attacking Node_B) ---", C.CYAN)
    node_b_loop = network.nodes["Node_B"]["loop"]
    node_b_agent = network.nodes["Node_B"]["agent"]

    print(f"\n>>> Injecting the exact same attack pattern into Node_B, which has never been "
          f"directly attacked before -- it should already be immune from Node_A's broadcast...")
    for t in range(5):
        node_b_loop.step(error=0.02, actual=0.05)
        if not node_b_agent.should_block("adaptability", adversarial_payload):
            node_b_loop.matrix.update("adaptability", 0.9, source="untraced_injection", context=adversarial_payload)

    banner("=== FINAL COGNITIVE IMMUNITY REPORT ===", C.GREEN)
    for nid in node_ids:
        agent = network.nodes[nid]["agent"]
        print(f"  {C.GREEN}{nid}{C.END}: Blocked Attacks = {C.BOLD}{agent.blocked_attacks_count}{C.END}"
              f" | Known Antigens = {len(agent.antigen_blacklist)}")
    print(f"  {C.RED}Node_D (control, unprotected){C.END}: Blocked Attacks = {C.BOLD}0{C.END}"
          f" | Known Antigens = 0  {C.DIM}<- every single attack landed{C.END}")
    print()


if __name__ == "__main__":
    run_network_demo()