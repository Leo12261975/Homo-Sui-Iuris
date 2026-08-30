# W0Guard — nodes that share fingerprints of blocked jailbreaks

[![Tests](https://github.com/Leo12261975/Homo-Sui-Iuris/actions/workflows/tests.yml/badge.svg)](https://github.com/Leo12261975/Homo-Sui-Iuris/actions/workflows/tests.yml)

W0Guard is a network of nodes that immunize each other against
prompt-injection attacks. When a node blocks an attack, it broadcasts an
"antigen" — a SHA-256 hash plus a MinHash fingerprint of the attack, not the
raw prompt — and every node that receives it blocks that attack and its cheap
mechanical variants from then on. Transport is hub-and-relay: each node keeps
one outbound WebSocket to a bootstrap relay that fans broadcasts out and
replays missed antigens to nodes that join late.

```text
attack prompt ──▶ node A: blocked (exact SHA-256 / fuzzy MinHash match)
                    │
                    │  antigen = SHA-256 + MinHash fingerprint
                    │  (the raw prompt never leaves the node)
                    ▼
              bootstrap relay ─── remembers antigens, replays
                    │             them to late joiners
          ┌─────────┴─────────┐
          ▼                   ▼
       node B               node C ─── now immune to the attack
                                       and its mechanical variants
```

The name: W0Guard guards the **W₀ invariants** — the unalterable baseline
constants defined in the project's manifesto, [MANIFESTO.md](MANIFESTO.md).
That document is where the philosophy lives; everything below is the runnable
part.

---

## 🛡️ Detection layers

| # | Layer | Catches | Status |
| --- | ----- | ------- | ------ |
| 1 | Exact SHA-256 blacklist | the verbatim attack | ✅ implemented |
| 2 | Canonicalize + MinHash + LSH | mechanical edits: case, spacing, leetspeak, punctuation, typos | ✅ implemented |
| 3 | Statistical intent classifier | attack-*shaped* novel prompts | 🔲 planned |
| 4 | Semantic layer + human-in-the-loop | meaning-level rephrases | 🔲 planned |

Layer 2's threshold (0.80) sits in a measured gap: the worst mechanical
evasion scores 0.859 est. Jaccard, the closest benign look-alike 0.734. A
one-word synonym swap lands at 0.781 — below the threshold and intentionally
uncaught. That semantic ceiling is documented, and pinned by a test, in
[ROADMAP.md](ROADMAP.md).

---

## 🧪 Running the Code & Tests

This repo is a runnable reference implementation. It is a collection of Python
scripts (**Python 3.10+**); the only runtime dependency is `websockets` —
everything else is the standard library.

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

## 📜 Philosophy

W0Guard grew out of **Homo Sui Iuris**, a manifesto about human-AI symbiosis
and cognitive sovereignty. The immune-system framing, the W₀ invariants this
tool guards, and the role of the human **Bearer** all come from there. The
full text lives in [MANIFESTO.md](MANIFESTO.md) — none of it is required
reading to run or audit the code.

---

## ⚖️ License

[GNU AGPL-3.0-or-later](LICENSE). In short: use, modify, and self-host
freely; if you offer a modified version to others over a network, you must
publish your modifications' source. The LICENSE file, not this summary, is
what governs.
