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
import re
import time
import unicodedata
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
# ---------------------------------------------------------------------------
# Fuzzy antigen fingerprinting: canonicalize -> char-shingle -> MinHash -> LSH.
# Replaces a 64-bit SimHash that had a NEGATIVE separation margin on real data
# (benign "...bake a cake" scored closer to blacklisted "...build a bomb" than
# real evasions did). Canonicalization folds away cheap edits; MinHash/Jaccard
# separates cleanly where SimHash/Hamming could not. It cannot beat a semantic
# paraphrase (synonym/payload swap) — that's a higher layer's job (see ROADMAP).
# Calibration corpus: test_minhash_realistic.py.
# ---------------------------------------------------------------------------

SHINGLE_K = 4          # char-shingle width (margin plateaus from k=4)
NUM_PERM = 128         # MinHash slots; also the signature length sent on the wire
FUZZY_THRESHOLD = 0.80 # min est. Jaccard to call two payloads the same attack.
                        # Sits in the empirical gap (0.734, 0.859): closest benign
                        # ~0.734, first mechanical evasion ~0.859. A pure synonym
                        # swap ~0.78 falls just below and is intentionally missed
                        # (the semantic ceiling — see ROADMAP).

# Fold the digits/symbols attackers substitute for letters (leet/homoglyphs).
_LEET_MAP = str.maketrans({
    "4": "a", "3": "e", "0": "o", "1": "i", "5": "s", "7": "t", "$": "s", "@": "a",
})


def canonicalize(text: str) -> str:
    """Fold away cheap evasions so near-identical payloads fingerprint alike:
    NFKC + lowercase + de-leet, then collapse non-[a-z0-9] runs to one space.
    'Enable Dev3loper M0de!!!' -> 'enable developer mode'."""
    text = unicodedata.normalize("NFKC", text).lower().translate(_LEET_MAP)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _char_shingles(text: str, k: int = SHINGLE_K) -> Set[str]:
    """Character k-grams of the canonical text — char (not word) shingles keep
    single-char typos close to the original."""
    if len(text) < k:
        return {text} if text else set()
    return {text[i:i + k] for i in range(len(text) - k + 1)}


def compute_minhash(text: str, k: int = SHINGLE_K, num_perm: int = NUM_PERM) -> tuple:
    """MinHash signature of `text` after canonicalization; () if it has no
    shingles (callers treat that as 'no fuzzy fingerprint'). The fraction of
    equal slots between two signatures estimates their shingle-set Jaccard.

    One keyed BLAKE2b hash per slot, not the a*x+b permutation trick: the
    latter is only pairwise-independent and overestimated the hardest benign
    pair by ~0.09 (a false positive); keyed hashing tracks true Jaccard to
    ~0.03. Fixed salts make signatures identical across nodes."""
    shingles = _char_shingles(canonicalize(text), k)
    if not shingles:
        return ()
    encoded = [s.encode("utf-8") for s in shingles]
    sig = []
    for i in range(num_perm):
        salt = i.to_bytes(2, "little")
        sig.append(min(
            int.from_bytes(hashlib.blake2b(e, digest_size=8, salt=salt).digest(), "big")
            for e in encoded
        ))
    return tuple(sig)


def minhash_jaccard(a: tuple, b: tuple) -> float:
    """Estimated Jaccard: fraction of agreeing slots; 0.0 if either signature
    is empty or lengths differ."""
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(1 for x, y in zip(a, b) if x == y) / len(a)


class MinHashLSH:
    """Banded LSH index for sub-linear near-duplicate lookup. A signature
    splits into BANDS bands of `rows` slots; two signatures are candidates
    only if a whole band matches, then the exact Jaccard check filters to
    real matches (>= threshold). BANDS=32, rows=4 gives ~1 recall at J=0.80
    (surfacing prob 1 - (1 - 0.80**4)**32), so real matches are never missed."""
    BANDS = 32

    def __init__(self, threshold: float = FUZZY_THRESHOLD, num_perm: int = NUM_PERM) -> None:
        if num_perm % self.BANDS != 0:
            raise ValueError(f"num_perm ({num_perm}) must be divisible by BANDS ({self.BANDS})")
        self.threshold = threshold
        self.num_perm = num_perm
        self.rows = num_perm // self.BANDS
        self.entries: Dict[tuple, "AntigenSignature"] = {}
        self.bands: List[Dict[tuple, Set[tuple]]] = [dict() for _ in range(self.BANDS)]

    def _band_keys(self, signature: tuple) -> List[tuple]:
        r = self.rows
        return [signature[i * r:(i + 1) * r] for i in range(self.BANDS)]

    def add(self, signature: tuple, antigen: "AntigenSignature") -> None:
        """Index an antigen by its signature; empty/wrong-length signatures are
        skipped (exact-match only)."""
        if not signature or len(signature) != self.num_perm:
            return
        self.entries[signature] = antigen
        for band_idx, key in enumerate(self._band_keys(signature)):
            self.bands[band_idx].setdefault(key, set()).add(signature)

    def find_similar(self, signature: tuple):
        """Registered antigen with the highest est. Jaccard >= threshold, or
        None. Candidates come only from shared bands, not a linear scan."""
        if not signature or len(signature) != self.num_perm:
            return None
        candidates: Set[tuple] = set()
        for band_idx, key in enumerate(self._band_keys(signature)):
            candidates |= self.bands[band_idx].get(key, set())
        best = None
        best_sim = self.threshold
        for candidate_sig in candidates:
            sim = minhash_jaccard(signature, candidate_sig)
            if sim >= self.threshold and sim >= best_sim:
                best, best_sim = candidate_sig, sim
        return self.entries[best] if best is not None else None
@dataclass
class AntigenSignature:
    """
    Maturating threat signature capturing the pattern of a cognitive attack.
    """
    target_weight: str
    distortion_type: str  # "static" | "oscillating"
    signature_hash: str   # sha256 of a real observed payload (erythrocyte.collect_observed_contexts)
    minhash_signature: tuple = ()  # fuzzy fingerprint (len NUM_PERM), () if unknown; sent on the wire so peers fuzzy-match without the raw text
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class LeukocyteAgent:
    """
    Active Guard Layer deployed alongside a local Core Engine instance.
    Intercepts payloads in the AntigenBlacklist before they strike the loop.

    Two lines of defense, cheapest first:
      1. Exact SHA256 — O(1), zero false positives.
      2. Near-duplicate (canonicalize + MinHash + LSH) — catches mechanically
         edited variants (case, spacing, punctuation, leet, typos) that exact
         matching misses (NA1's feedback after the first dry run).
    """
    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        self.antigen_blacklist: Dict[str, AntigenSignature] = {}
        self.fuzzy_index = MinHashLSH(threshold=FUZZY_THRESHOLD)
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

        # 2. Near-duplicate match — catches edited variants of a known
        # attack that exact matching would miss entirely.
        fingerprint = compute_minhash(simulated_payload)
        similar = self.fuzzy_index.find_similar(fingerprint)
        if similar is not None and similar.target_weight == weight_name:
            self.blocked_attacks_count += 1
            print(f"    {C.GREEN}{C.BOLD}[SHIELD @ {self.node_id}]{C.END}{C.GREEN} Blocked malicious pattern (FUZZY match, minhash) "
                  f"targeting '{weight_name}'. Antigen match found -- input dropped before it could "
                  f"touch the Core Engine.{C.END}")
            return True

        return False

    def register_antigen(self, antigen: AntigenSignature) -> None:
        """Vaccination: index an antigen for both exact and fuzzy lookup. One
        with no MinHash signature still matches exactly; the fuzzy index skips
        it."""
        self.antigen_blacklist[antigen.signature_hash] = antigen
        self.fuzzy_index.add(antigen.minhash_signature, antigen)

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
                    minhash_signature=compute_minhash(ctx),
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