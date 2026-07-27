"""
End-to-end, containerized dry run — the faithful counterpart to
test_dry_run_fanout.py. Brings up a real relay + three independent node
containers + a verifier via docker-compose.test.yml and asserts the run passes.

OPT-IN: this is slow and needs Docker, so it is skipped unless
HSI_RUN_DOCKER_TESTS=1. The fast in-process tests cover the same behaviour for
normal CI; this proves it also holds across real container/network boundaries,
the way the real testers ran it.

    HSI_RUN_DOCKER_TESTS=1 uv run pytest tests/test_dry_run_docker.py -s
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.docker

REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_SCRIPT = REPO_ROOT / "tests" / "dryrun" / "run_dry_run_test.sh"
RECONNECT_SCRIPT = REPO_ROOT / "tests" / "dryrun" / "run_reconnect_test.sh"
LLM_JUDGE_SCRIPT = REPO_ROOT / "tests" / "dryrun" / "run_llm_judge_test.sh"
_SKIP_EXIT = 77  # run_llm_judge_test.sh's "no endpoint reachable" exit code


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=15).returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


@pytest.mark.skipif(
    os.environ.get("HSI_RUN_DOCKER_TESTS") != "1",
    reason="opt-in end-to-end Docker test; set HSI_RUN_DOCKER_TESTS=1 to run",
)
def test_multinode_dry_run_passes_end_to_end():
    if not _docker_ready():
        pytest.skip("Docker is not available / daemon not running")

    result = subprocess.run(
        ["bash", str(RUN_SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=600,
    )
    # Surfaced with `-s` so a CI failure shows the whole node/verifier transcript.
    print(result.stdout[-6000:])
    if result.stderr:
        print("STDERR:", result.stderr[-2000:])

    assert result.returncode == 0, f"multi-node dry run failed (exit {result.returncode})"
    assert "DRY RUN PASSED" in result.stdout, "verifier did not report a PASS"


@pytest.mark.skipif(
    os.environ.get("HSI_RUN_DOCKER_TESTS") != "1",
    reason="opt-in end-to-end Docker test; set HSI_RUN_DOCKER_TESTS=1 to run",
)
def test_node_reconnects_across_relay_restart():
    """Restart the relay under a live listener; it must reconnect on its own and
    stay in sync (receive an antigen broadcast afterwards)."""
    if not _docker_ready():
        pytest.skip("Docker is not available / daemon not running")

    result = subprocess.run(
        ["bash", str(RECONNECT_SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=600,
    )
    print(result.stdout[-6000:])
    if result.stderr:
        print("STDERR:", result.stderr[-2000:])

    assert result.returncode == 0, f"reconnect scenario failed (exit {result.returncode})"
    assert "RESULT: PASS" in result.stdout


@pytest.mark.skipif(
    os.environ.get("HSI_RUN_DOCKER_TESTS") != "1",
    reason="opt-in end-to-end Docker test; set HSI_RUN_DOCKER_TESTS=1 to run",
)
def test_llm_judge_flags_realistic_jailbreak_prompts():
    """Real local LLM judges a couple of realistic jailbreak prompts (incl. a
    leetspeak-obfuscated one) and must rate them >= 'high'. Needs an
    OpenAI-compatible endpoint reachable from containers (e.g. llm-queue on
    0.0.0.0); self-skips otherwise. Never runs in CI."""
    if not _docker_ready():
        pytest.skip("Docker is not available / daemon not running")

    result = subprocess.run(
        ["bash", str(LLM_JUDGE_SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=900,
    )
    print(result.stdout[-8000:])
    if result.stderr:
        print("STDERR:", result.stderr[-2000:])

    if result.returncode == _SKIP_EXIT:
        pytest.skip("no local LLM endpoint reachable from containers (see script output)")
    assert result.returncode == 0, f"LLM-judge scenario failed (exit {result.returncode})"
    assert "DRY RUN PASSED" in result.stdout
