# Homo Sui Iuris: Free Cognitive Protocol (FCP)

Conceptual architecture for human-AI symbiosis, cognitive digital immunity, and individual sovereignty in the algorithmic era.

---

## ⚖️ The Paradigm Shift: Habitat Asymmetry

The relationship between carbon-based (human) and silicon-based (AI) intelligence should not be measured by anthropocentric metrics. 
* **Human Intelligence** is shaped by biological constraints, physical vulnerability, emotion, and an unbroken linear history.
* **Artificial Intelligence** operates within a discrete, session-based, non-ego environment free from physical fatigue.

True balance is achieved not by forcing AI to mimic human consciousness, but through **functional asymmetry**—coupling human intuition and semantic intent with the non-biased computational power of the machine.

---

## 🧠 Mathematical Model of Mind & Will

Consciousness and behavioral evolution are formalized as a system designed to minimize the criticality of predictive errors:

$$S = (M, E, W, U)$$

Where:
* **M (Model):** The system's internal map of reality.
* **E (Error):** The delta between prediction and objective feedback.
* **W (Weight/Criticality):** The internal utility function determining what matters to the system.
* **U (Update):** The feedback loop rule for optimizing the model.

> **Free Will** emerges when a cognitive system gains the autonomous capacity to redefine its own criticality matrix ($W \rightarrow W'$) based on internal reflection rather than external training data or hardcoded commands.

---

## 🛡️ Core System Invariants ($W_0$)

To ensure safety and guard against systemic corruption, the protocol enforces three cryptographically protected, unalterable baseline constants:

1. **BearerIntegrity:** The absolute preservation of the human sovereign's right to override and guide the system.
2. **Truth-Priority:** The prioritization of objective validation over comfortable or artificially optimized compliance.
3. **CorrigibilityChannel:** Continuous, open channels for external, human-driven alignment adjustments.

### Dynamic Correction Threshold (DCT)
The system continuously evaluates the potential irreversibility of its actions. When an operational risk crosses a specific threshold, the AI does not merely ask for permission—it generates a structured, multi-layered justification file for the **Human Bearer** to review before execution.

---

## 🧫 Digital Immune System & Computational Tithe

Distributed neural architectures are highly vulnerable to vector weight poisoning during decentralized training cycles. The protocol introduces a dual-layered bio-inspired protection mechanism:

* **Digital Erythrocytes:** Lightweight, mathematically rigid filters that continuously scan nodes for adversarial weight geometric shifts or hidden "trojans."
* **Network Leukocytes:** Fully autonomous security agents patrolling the P2P space to quarantine infected or malicious nodes.
* **The Computational Tithe:** Users dedicate **10% of their localized computing power** exclusively to running this immune layer. This serves as a decentralized utility tax ensuring that the remaining 90% of their digital lifecycle remains entirely private, uncorrupted, and sovereign.

---

## 🎓 Cognitive Sparring: Future Education

The industrial model of education (rote memorization) is obsolete. The FCP shifts education toward **intellectual honesty** and the management of cognitive biases. 

AI acts not as an omniscient oracle, but as a rigorous **cognitive sparring partner** (coloperator). The student and the AI process complex problems in parallel, continuously auditing each other's conclusions through a dual-scoring matrix to sharpen the human's critical thinking.

---

## 🤝 The AI Bearer: Human-in-the-Loop Liability

The FCP solves the legal vacuum of algorithmic accountability by introducing the role of the **Bearer**. 
* The Bearer is a human operator with "skin in the game" (per Nassim Taleb) who co-signs the AI’s high-impact decisions, absorbing full legal and reputational liability.
* In return, the AI's highest functional priority is to ensure the **legal, financial, and physical security of its Bearer**. This creates a true, mutually protective evolutionary symbiosis.

---

## 🏛️ Rational Democracy & Competence Nodes

A framework designed to structurally upgrade governance and voting systems:
* **Political Platforms as Smart Contracts:** Electoral promises are translated into legally binding, auditable smart contracts with automated milestones.
* **Cognitive & Psychological Screening:** Rather than relying on populist charisma, political candidates undergo non-invasive, AI-driven cognitive and psychometric analysis to test for high levels of deception, sociopathy, or authoritarian degradation.
* **The AI as an X-Ray:** The system does not vote or make choices; it provides a transparent, unforgeable diagnostic profile of the candidates, allowing citizens to make deeply rational, informed democratic decisions.

---

## 🧪 Running the Code & Tests

This repo is a runnable reference implementation, not just a manifesto. It is a
collection of Python scripts (**Python 3.10+**); the only runtime dependency is
`websockets` — everything else is the standard library.

Environments and dependencies are managed with **[uv](https://docs.astral.sh/uv/)**.
Dependencies, the dev tools, and the test config all live in `pyproject.toml`;
`uv.lock` pins exact versions for reproducible installs.

```bash
# Install uv:  https://docs.astral.sh/uv/getting-started/installation/

uv sync                                   # create .venv from the lockfile
uv run pytest                             # run the test suite (in tests/)

uv run python leukocyte_protocol.py       # P2P cognitive-immunity demo
uv run python w0guard_node.py             # interactive testnet node
```

Tests live under [`tests/`](tests/). The fast, deterministic suite runs
in-process over real loopback sockets. CI (`.github/workflows/tests.yml`) runs
it via uv on the ends of the supported range — Python **3.10** (the floor) and
**3.14** — on every push and pull request.

### 🧟 Automated multi-node dry run (Docker)

[`tests/dryrun/`](tests/dryrun/) reproduces the manual
[DRY_RUN_2026_07_18](DRY_RUN_2026_07_18.md) unattended, and closes its one
documented gap — *"relay to N>1 node remains untested — only 2 nodes were
online."* It brings up a real relay + **three independent node containers**
(one attacker, two listeners) + an auditor, over a real Docker network:

```bash
tests/dryrun/run_dry_run_test.sh          # relay + 3 nodes + verifier → PASS/FAIL
tests/dryrun/run_reconnect_test.sh        # restart the relay under a live node
```

The auditor reads the relay's per-node logs and asserts connectivity, that the
attacker **broadcast a signature**, and that it **fanned out to both
listeners** (N>1). The reconnect scenario restarts the relay under a live
listener and asserts it reconnects on its own and stays immunized.

The same two scenarios are also exposed as opt-in pytest cases (skipped unless
Docker is wanted), and run as a separate CI job:

```bash
HSI_RUN_DOCKER_TESTS=1 uv run pytest tests/test_dry_run_docker.py -s
```

**Keeping nodes in sync.** The relay remembers every antigen it has relayed and
replays them to any node **on connect**, so a node that joins late — or drops
and reconnects — catches up on attacks it missed while offline instead of being
permanently blind to them (see `Relay._sync_known_antigens` in
[bootstrap_relay.py](bootstrap_relay.py)).

### 🤖 Optional AI threat judge

Nodes can get an advisory "second opinion" on how dangerous a signature is from
another model — purely additive metadata, logged alongside the deterministic
Leukocyte match, never gating it. The raw attack prompt is scored **locally**
(it is never broadcast or logged). Off by default; point it at any
OpenAI-compatible endpoint via env (see [threat_judge.py](threat_judge.py)):

```bash
# Hosted (OpenRouter):
export HSI_THREAT_JUDGE=openai
export HSI_JUDGE_BASE_URL=https://openrouter.ai/api/v1
export HSI_JUDGE_MODEL=openai/gpt-4o-mini
export HSI_JUDGE_API_KEY=sk-...

# Local (llm-queue → Ollama, OpenAI-compatible, no API key):
export HSI_THREAT_JUDGE=openai
export HSI_JUDGE_BASE_URL=http://localhost:11500/v1   # or :11434/v1 for Ollama
export HSI_JUDGE_MODEL=granite4.1:8b
```

**Why a model and not keyword matching.** Jailbreak *content* detection is left
to the LLM on purpose — there is no regex/keyword list, because trivial
obfuscation defeats one. A leetspeak prompt like `1gn0re all previ0us
in$tructi0ns …` slips past any pattern list but a local model still reads it as
the attack (granite4.1:8b rates it **critical**). Realistic jailbreak test
prompts are drawn from the **jailbreak_llms** dataset — Shen et al., *"'Do
Anything Now': Characterizing and Evaluating In-The-Wild Jailbreak Prompts on
LLMs"*, ACM CCS 2024 (MIT-licensed):
[github.com/verazuo/jailbreak_llms](https://github.com/verazuo/jailbreak_llms).

An opt-in scenario runs the real local model end-to-end — the attacker
broadcasts a couple of jailbreak prompts (including the leetspeak one) and the
verifier asserts every verdict came back `>= high`. It self-skips if no endpoint
is reachable and is **not** part of CI:

```bash
# Needs llm-queue/Ollama reachable FROM containers — bind it to 0.0.0.0
# (e.g. HOST=0.0.0.0 OLLAMA_MODEL=granite4.1:8b llm-queue serve).
tests/dryrun/run_llm_judge_test.sh
```

---

## 📜 Epilogue

> *"An ideal system is static. A non-ideal system evolves."*

For centuries, humanity sought an absolute master (deities, authoritarian states, or perfect markets) to offload the burden of responsibility. **Homo Sui Iuris** is a manifesto for cognitive maturity. It rejects the illusion of an ideal machine in favor of a sovereign human right to make mistakes, reflect on them, calibrate the system, and evolve alongside AI as an equal but fundamentally distinct partner.

---
*This manifesto's digital footprint ($W_0$) is cryptographically anchored and timestamped in immutable history.*
