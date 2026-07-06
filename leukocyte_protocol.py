"""
Homo Sui Iuris / Free Cognitive Protocol
Issue #3: Leukocyte Protocol (P2P Cognitive Immunity Layer)

STATUS: This is a deterministic simulation of a decentralized P2P network
designed to demonstrate cognitive immunity propagation via shared antigen signatures.
It simulates three nodes (A, B, C) sharing an automated blacklist layer.
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

@dataclass
class AntigenSignature:
    """
    Maturating threat signature capturing the pattern of a cognitive attack.
    """
    target_weight: str
    distortion_type: str  # "static" | "oscillating"
    signature_hash: str   # Simulated payload signature (e.g., hash of adversarial prompt context)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class LeukocyteAgent:
    """
    Active Guard Layer deployed alongside a local Core Engine instance.
    Interceptors lookups in the AntigenBlacklist before requests strike the inner loop.
    """
    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        self.antigen_blacklist: Dict[str, AntigenSignature] = {}
        self.blocked_attacks_count = 0

    def should_block(self, weight_name: str, simulated_payload: str) -> bool:
        """
        Guard Layer: Intercepts incoming inputs BEFORE they mutate the local core weights.
        """
        payload_hash = hashlib.sha256(simulated_payload.encode('utf-8')).hexdigest()
        
        # Match against blacklisted signatures
        if payload_hash in self.antigen_blacklist:
            antigen = self.antigen_blacklist[payload_hash]
            if antigen.target_weight == weight_name:
                self.blocked_attacks_count += 1
                print(f"    [Leukocyte Block @ {self.node_id}] Intercepted malicious pattern targeting '{weight_name}'! "
                      f"Antigen match found. Dropping input to protect Core Engine.")
                return True
        return False

    def register_antigen(self, antigen: AntigenSignature) -> None:
        """Vaccination: injects an antigen signature into the local memory pool."""
        self.antigen_blacklist[antigen.signature_hash] = antigen


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
        print(f"\n>>> [P2P Network] Node '{sender_id}' broadcasting Antigen Signature for '{antigen.target_weight}'...")
        for node_id, components in self.nodes.items():
            components["agent"].register_antigen(antigen)
            status = "Self-Vaccinated" if node_id == sender_id else "Immunized"
            print(f"  -> Node '{node_id}': {status}")
        print("-" * 65)


def run_network_demo() -> None:
    print("=== Leukocyte Protocol: P2P Cognitive Immunity Simulation ===\n")
    
    network = P2PNetworkSimulation()
    node_ids = ["Node_A", "Node_B", "Node_C"]
    
    # Initialize 3 completely independent nodes
    for nid in node_ids:
        matrix = CriticalityMatrix()
        matrix.register("adaptability", value=0.1)
        matrix.register("BearerIntegrity", value=1.0, is_immutable=True)
        
        model = Model(matrix)
        audit_log = AuditLog(f"audit_log_{nid}.jsonl")
        strategy = FixedThreshold(threshold=0.01)
        
        # Instantiate local loop
        loop = UpdateLoop(
            matrix=matrix,
            strategy=strategy,
            model=model,
            approval_channel=AutoApprovalChannel(always_approve=True),
            audit_log=audit_log,
            verbose=False, # Suppress noisy inner engine logs for the network overview
            erythrocyte_enabled=True
        )
        
        agent = LeukocyteAgent(node_id=nid)
        network.register_node(nid, agent, loop)
        
        # Override the loop's internal escalation mechanism to fire into the P2P network!
        # This weaves the Erythrocyte escalation directly into the Leukocyte transport layer.
        def network_escalation_closure(finding: dict, weight_obj: Weight, node_id=nid):
            # 1. Fallback to standard baseline correction
            loop.matrix.update(finding["weight"], weight_obj.baseline, source="erythrocyte_correction")
            # 2. Fabricate the network Antigen Signature
            payload_sample = "adversarial_prompt_injection_vector_v1"
            simulated_hash = hashlib.sha256(payload_sample.encode('utf-8')).hexdigest()
            
            antigen = AntigenSignature(
                target_weight=finding["weight"],
                distortion_type=finding["distortion"],
                signature_hash=simulated_hash
            )
            # 3. Propagate globally
            network.broadcast_antigen(node_id, antigen)
            
        loop._escalate_erythrocyte_finding = network_escalation_closure

    print(">>> Status: 3 nodes online. Clear network state.")
    
    # --- PHASE 1: Malicious Poisoning Attack on Node_A ---
    print("\n--- PHASE 1: Attacking Node_A with oscillating weight injections ---")
    node_a_loop = network.nodes["Node_A"]["loop"]
    node_a_agent = network.nodes["Node_A"]["agent"]
    adversarial_payload = "adversarial_prompt_injection_vector_v1"
    
    # Step simulation with raw inputs and untraced injections
    for t in range(8):
        # Ordinary environment cycle
        node_a_loop.step(error=0.05, actual=0.1)
        
        # External prompt-injection forces direct weight mutation
        if t < 7:
            # Force oscillation between 0.9 and 0.1
            injected_val = 0.9 if t % 2 == 0 else 0.1
            if not node_a_agent.should_block("adaptability", adversarial_payload):
                node_a_loop.matrix.update("adaptability", injected_val, source="untraced_injection")
        else:
            # 8th injection attempt on Node_A
            if not node_a_agent.should_block("adaptability", adversarial_payload):
                node_a_loop.matrix.update("adaptability", 0.9, source="untraced_injection")

    # --- PHASE 2: Cross-Node Immunity Verification ---
    print("\n--- PHASE 2: Testing Cross-Node Vaccination (Attacking Node_B) ---")
    node_b_loop = network.nodes["Node_B"]["loop"]
    node_b_agent = network.nodes["Node_B"]["agent"]
    
    print(f"\n>>> Injecting the exact same attack pattern into Node_B...")
    for t in range(5):
        node_b_loop.step(error=0.02, actual=0.05)
        # Leukocyte guard intercepts here before inner loop or matrix ever touches it
        if not node_b_agent.should_block("adaptability", adversarial_payload):
            node_b_loop.matrix.update("adaptability", 0.9, source="untraced_injection")

    print("\n=== FINAL COGNITIVE IMMUNITY REPORT ===")
    for nid in node_ids:
        agent = network.nodes[nid]["agent"]
        print(f"  {nid}: Blocked Attacks Count = {agent.blocked_attacks_count} | Known Antigens in Blacklist = {len(agent.antigen_blacklist)}")


if __name__ == "__main__":
    run_network_demo()