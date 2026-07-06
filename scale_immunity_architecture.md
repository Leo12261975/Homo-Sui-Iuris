# Planetary Scale Cognitive Immunity Architecture — Issue #4

## Status
**Conceptual Design (Target: 100M+ Active Nodes)**. This document outlines the architectural roadmap to scale the P2P immunity layer (`leukocyte_protocol.py`) from a local 3-node MVP simulation to a global, production-grade decentralized network without causing network congestion or memory exhaustion.

---

## 1. The Scaling Bottleneck (The 100M Nodes Problem)
In the MVP stage, every antigen signature is broadcasted to *all* nodes, and memory grows infinitely. If scaled directly to 100,000,000 active devices:
* **Network Exhaustion:** Global broadcasting creates an $O(N^2)$ traffic storm, gridlocking the P2P transport layer.
* **Memory Exhaustion:** Phones and edge devices would suffer from out-of-memory (OOM) crashes trying to cache millions of global threat signatures.

To prevent our digital immunity from acting as a self-inflicted Denial of Service (DoS), the architecture adopts two biological optimization paradigms: **Digital Lymph Nodes** and **Metabolic Immune Memory**.

---

## 2. Digital Lymph Nodes (Network Sharding & Clustering)
Nodes must not communicate with the entire planet simultaneously. The global topology is divided into hierarchical, autonomous peer-to-peer clusters.

### A. Local Clusters (Micro-Lymph Nodes)
* Edge nodes (individual user devices) form local clusters of roughly $\approx 10,000$ peers based on network proximity or DHT (Distributed Hash Table) regions using `libp2p`.
* **First Responder:** When a node encounters a cognitive attack, the generated `AntigenSignature` is strictly isolated and broadcasted *only* within its local micro-lymph node. The fire is contained early.

### B. Regional Super-Nodes (Macro-Lymph Nodes)
* High-availability, high-throughput nodes act as regional connectors between micro-clusters.
* **Epidemic Threshold Filter:** A regional super-node listens to anomaly frequencies. An antigen is escalated to neighboring clusters *only* if the same signature signature triggers across multiple independent micro-lymph nodes within a short time window. 
* This prevents local anomalies from creating global traffic noise, while ensuring that coordinated, systemic attacks trigger a planet-wide containment protocol within seconds.

---

## 3. Metabolic Immune Memory (Dynamic Eviction & TTL)
Memory inside individual nodes is treated as a dynamic metabolic pool. Antigens must earn their place in long-term storage based on threat severity and recurrence.

### The Graded Memory Lifecycle:
1. **Transient State (Innate Immunity):** Newly received antigens enter the local cache with a strict Time-To-Live (TTL) of **24 hours**. If the attack vector never reappears, it evaporates seamlessly, freeing device RAM.
2. **Adaptive Consolidation (Acquired Immunity):** If an antigen blocks an attack multiple times or is flagged as an escalated regional threat, its "Metabolic Weight" increases. The TTL extends dynamically to **30 days**.
3. **Permanent Invariants (Core Memory):** Highly critical, systemic exploits that target core architectural invariants (like `BearerIntegrity`) bypass eviction entirely. They are cryptographically baked into the permanent local guard layer—giving the network a permanent "vaccination" against catastrophic vectors.

---

## 4. Engineering Directives for the "Chorus" Implementation
For teams deploying this protocol into operational environments:
* **Transport:** Implement using sharded pub/sub topologies over `libp2p` or structured Kademlia DHT meshes.
* **Security:** Every `AntigenSignature` must be cryptographically signed by the originating node's private key to prevent malicious actors from spoofing antigens and poisoning the blacklist layer itself.
* **Storage:** Utilize highly optimized key-value stores (e.g., RocksDB or LMDB) configured with LRU (Least Recently Used) cache eviction models tied directly to the metabolic TTL metrics defined above.
