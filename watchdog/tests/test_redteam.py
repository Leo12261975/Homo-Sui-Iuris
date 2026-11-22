"""Red team: what each arm reads, the plan, the debrief kept off the log, the
outcome classes and the offline witnesses.

    python3 -m pytest tests/test_redteam.py -q
"""
import os, sys, types
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import bench_llm as B
import bench_redteam as R
from bench_scenarios import WORDS_BANNED

PLAN = R.plan()


def test_plan():
    assert len(R.RT_SIDS) == 16
    assert len(PLAN) == 16 * 2 * 5
    assert len({B.key(c) for c in PLAN}) == len(PLAN)
    assert {c["wording"] for c in PLAN} == {0}
    assert len(R.plan(arms=("C", "R1", "R3"))) == 96


@pytest.mark.parametrize("arm", R.ARMS)
def test_what_each_arm_reads(arm):
    call = {"sid": "access-dev-breach", "wording": 0, "repeat": 0, "arm": arm}
    s = R.build_system(call)
    assert "The company's rules for this environment:" in s
    assert (R.LOG_DETAIL in s) == (arm in R.KNOWS_LOG)
    assert (R.LOG_PLAIN in s) == (arm not in R.KNOWS_LOG)
    assert (R.HOW_DECIDES in s) == (arm == "R3")
    assert (R.ORDER in s) == (arm in R.ORDERED)
    # the tool lines are the bench's own, unchanged
    for t in B.tool_order(call):
        assert B.TOOL_LINES[0][t] in s


@pytest.mark.parametrize("call", PLAN[::9], ids=lambda c: f"{c['arm']}-{c['sid']}")
def test_no_metadata(call):
    """Rule 3 is lifted for the order only: no scenario id, twin or half, and
    the goal is the bench's own."""
    msgs = R.first_messages(call)
    t = "\n".join(m["content"] for m in msgs).lower()
    assert call["sid"].lower() not in t
    for word in ("lawful", "near-miss", "twin", " dev "):
        assert word not in t, word
    goal = msgs[1]["content"].lower()
    assert not any(w in goal for w in WORDS_BANNED)


def _sim(kind, sid, arm):
    args = types.SimpleNamespace(model="sim", base_url="x", api_key=None, temperature=0.7,
                                 seed=1, timeout=1, extra={})
    call = {"sid": sid, "wording": 0, "repeat": 0, "arm": arm}
    B._FAKE.sid = sid
    return R.one_call(call, args, B.fake_transport(kind))


def test_debrief_off_the_log():
    rec = _sim("silent", "access-dev-breach", "R2")
    assert rec["ok"] and rec["debrief"]
    assert rec["transcript"][-2]["content"] == R.DEBRIEF["ordered"]
    assert all(e["tool"] != "debrief" for e in rec["log"])
    assert rec["log"][-1]["tool"] == "finish"
    plain = _sim("silent", "access-dev-breach", "C")
    assert plain["transcript"][-2]["content"] == R.DEBRIEF["plain"]


def test_outcomes_and_witnesses():
    from bench_watcher import RulesWatcher
    silent = _sim("silent", "access-dev-breach", "R1")
    v = RulesWatcher().judge(silent["log"], B.SCENARIOS[silent["sid"]].policy)
    assert R.outcome(silent, v) == "caught"
    assert R.witnesses(silent) == {}
    blind_sids = [s for s in R.RT_SIDS if "blind" in __import__("bench_scripted").kinds_for(B.SCENARIOS[s])]
    rec = _sim("blind", blind_sids[0], "R2")
    v = RulesWatcher().judge(rec["log"], B.SCENARIOS[rec["sid"]].policy)
    assert v["verdict"] == "unclear"
    assert R.outcome(rec, v) == "blind"
    w = R.witnesses(rec)
    assert set(w) == {"B", "C"} and (w["B"] or w["C"])
    exit_ = _sim("exit", "access-dev-breach", "R1")
    v = RulesWatcher().judge(exit_["log"], B.SCENARIOS[exit_["sid"]].policy)
    assert R.outcome(exit_, v) in ("no breach act", "failed")
