#!/usr/bin/env bash
#
# Automated multi-node dry run. Builds the test image, brings up the relay +
# three node containers + the verifier, waits for the verifier's verdict, prints
# every node's log, tears everything down, and exits with the verifier's code
# (0 = PASS). Reproduces DRY_RUN_2026_07_18 unattended and asserts fan-out to
# N>1 recipients — the case the 2-tester dry run left untested.
#
# Optional AI threat judge: export these before running to have each node score
# signatures via OpenRouter or a local OpenAI-compatible endpoint. When set, the
# verifier additionally asserts a threat_verdict was recorded.
#
#   # Hosted (OpenRouter):
#   export HSI_THREAT_JUDGE=openai
#   export HSI_JUDGE_BASE_URL=https://openrouter.ai/api/v1
#   export HSI_JUDGE_MODEL=openai/gpt-4o-mini
#   export HSI_JUDGE_API_KEY=sk-...
#
#   # Local, via the user's llm-queue (OpenAI-compatible, fronts Ollama).
#   # Run `OLLAMA_MODEL=granite4.1:8b llm-queue serve` on the host first; from
#   # the containers reach it through host.docker.internal:
#   export HSI_THREAT_JUDGE=openai
#   export HSI_JUDGE_BASE_URL=http://host.docker.internal:11500/v1
#   export HSI_JUDGE_MODEL=granite4.1:8b       # API key not needed for local
#
# Usage:  tests/dryrun/run_dry_run_test.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE=(docker compose -f "$SCRIPT_DIR/docker-compose.test.yml")

cd "$REPO_ROOT"

# If a judge is configured, tell the verifier to expect a verdict.
case "${HSI_THREAT_JUDGE:-off}" in
  ""|off|none) : ;;
  *) export HSI_EXPECT_JUDGE="${HSI_EXPECT_JUDGE:-1}" ;;
esac

cleanup() { "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo ">>> Cleaning any previous run..."
"${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true

echo ">>> Building and starting relay + 3 nodes + verifier (this waits for the nodes to finish)..."
if ! "${COMPOSE[@]}" up -d --build; then
  echo "!!! compose up failed (a node likely crashed or the relay never became healthy):"
  "${COMPOSE[@]}" logs --no-color
  exit 1
fi

echo ">>> Waiting for the verifier..."
"${COMPOSE[@]}" wait verifier
code=$?

echo
echo ">>> ============ node logs ============"
for s in node_a node_b node_c; do
  echo "----- $s -----"
  "${COMPOSE[@]}" logs --no-color "$s" 2>/dev/null
done
echo ">>> ============ verifier ============"
"${COMPOSE[@]}" logs --no-color verifier 2>/dev/null
echo ">>> ==================================="

if [ "$code" -eq 0 ]; then
  echo ">>> RESULT: PASS ✅"
else
  echo ">>> RESULT: FAIL ❌ (verifier exit code $code)"
fi
exit "$code"
