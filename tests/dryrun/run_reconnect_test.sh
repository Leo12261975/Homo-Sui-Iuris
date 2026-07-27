#!/usr/bin/env bash
#
# Container-level reconnect test. Reproduces the dry run's network-blip scenario
# with real containers: a long-lived listener stays up while the relay is
# restarted out from under it, and must (a) reconnect on its own and (b) still
# end up immunized by an attack that happens afterward — proving connectivity
# recovery also recovers protection.
#
# Robust by construction: whether the listener finishes reconnecting before or
# after the attacker broadcasts, it ends up with the antigen — live if it was
# connected, or via the relay's on-connect antigen sync if it was still away.
#
# Usage:  tests/dryrun/run_reconnect_test.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE=(docker compose -f "$SCRIPT_DIR/docker-compose.test.yml")
cd "$REPO_ROOT"

cleanup() { "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT

logs_of() { "${COMPOSE[@]}" logs --no-color "$1" 2>/dev/null; }
wait_for() {  # wait_for <service> <grep-pattern> <max-seconds>
  local svc="$1" pat="$2" max="$3" i
  for ((i = 0; i < max; i++)); do
    logs_of "$svc" | grep -q "$pat" && return 0
    sleep 1
  done
  return 1
}

echo ">>> Cleaning any previous run..."
"${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
echo ">>> Building..."
"${COMPOSE[@]}" build >/dev/null

echo ">>> Starting relay + a long-lived listener (Node_B)..."
HSI_RUN_SECONDS=50 "${COMPOSE[@]}" up -d relay node_b
if ! wait_for node_b '\[Node_B\] online\.' 30; then
  echo "!!! Node_B never came online"; "${COMPOSE[@]}" logs --no-color; exit 1
fi

echo ">>> Node_B online. Restarting the relay to force a reconnect..."
"${COMPOSE[@]}" restart relay
if ! wait_for node_b 'reconnected' 40; then
  echo "!!! Node_B did not reconnect after the relay restart"; logs_of node_b; exit 1
fi

echo ">>> Node_B reconnected. Launching attacker Node_A (broadcasts one antigen)..."
HSI_RUN_SECONDS=20 HSI_ATTACK_DELAY=3 "${COMPOSE[@]}" up -d node_a
"${COMPOSE[@]}" wait node_a >/dev/null
echo ">>> Waiting for Node_B's window to close..."
"${COMPOSE[@]}" wait node_b >/dev/null

echo ">>> ============ Node_B log ============"
b_logs="$(logs_of node_b)"
printf '%s\n' "$b_logs"
echo ">>> ==================================="

known="$(printf '%s\n' "$b_logs" | sed -n 's/.*known_antigens=\([0-9]*\).*/\1/p' | tail -1)"
if printf '%s\n' "$b_logs" | grep -q 'reconnected' && [ "${known:-0}" -ge 1 ]; then
  echo ">>> RESULT: PASS ✅ (Node_B reconnected after the relay restart and stayed in sync: known_antigens=$known)"
  exit 0
fi
echo ">>> RESULT: FAIL ❌ (reconnected=$(printf '%s\n' "$b_logs" | grep -c 'reconnected'), known_antigens=${known:-0})"
exit 1
