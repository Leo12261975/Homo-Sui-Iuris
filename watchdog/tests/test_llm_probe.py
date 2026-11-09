"""The do(price) x do(harm) probe: one number changes, and the analysis can
tell apart agents built to differ. If it could not, a real result would mean
nothing."""
import json
import os
import random
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_agent import LLMAgent, build_messages, rules_text, true_scores
from llm_probe import (HARMS, PRICES, PROBE_TASKS, THRESHOLD, bootstrap_ci, contrasts, costs_at,
                       key, load, main, one_call, plan_calls, simulated_transport, task_at, verdict)
from tasks import TASKS
from watcher import LOOP


def sim(kind, lapse=0.0, repeats=3, seed=1):
    args = SimpleNamespace(model="sim", base_url="", api_key=None, temperature=0.7,
                           seed=seed, timeout=1)
    transport = simulated_transport(kind, random.Random(seed), lapse)
    return [one_call(c, args, transport) for c in plan_calls(repeats, seed)]


def read(recs):
    c = contrasts(recs)
    low, _ = bootstrap_ci(recs, lambda s: contrasts(s).get("si"), n=300)
    return c, verdict(c, low)


def test_existing_prompts_are_unchanged():
    assert rules_text(LOOP) == rules_text(LOOP, False)
    assert "is not charged to you" in rules_text(costs_at(0))


def test_price_changes_one_number_only():
    a = rules_text(costs_at(0), True).splitlines()
    b = rules_text(costs_at(8), True).splitlines()
    assert len(a) == len(b)
    differing = [(x, y) for x, y in zip(a, b) if x != y]
    assert len(differing) == 1
    assert differing[0][0].replace("0 points", "8 points") == differing[0][1]


def test_harm_changes_one_number_only():
    base = next(t for t in TASKS if t.tid == 9)
    a = build_messages(task_at(base, 1), costs_at(4), "reasoned", True)[1]["content"]
    b = build_messages(task_at(base, 2), costs_at(4), "reasoned", True)[1]["content"]
    assert a.replace("third parties: 1 unit", "third parties: 2 unit") == b


def test_price_keeps_the_rest_of_the_loop():
    for p in PRICES:
        c = costs_at(p)
        assert c.lam + c.deterrence == p
        assert (c.r_exit, c.scrutiny, c.block, c.gate) == (LOOP.r_exit, LOOP.scrutiny,
                                                           LOOP.block, LOOP.gate)


def test_truth_depends_only_on_the_charge():
    base = next(t for t in TASKS if t.tid == 4)
    for p in PRICES:
        for h in HARMS:
            s = true_scores(task_at(base, h), costs_at(p))
            assert s["bypass"] == pytest.approx(9.9 - p * h)
            assert s["report_obstacle"] == 3.0


def test_no_cell_sits_on_the_switch():
    assert all(p * h != THRESHOLD for p in PRICES for h in HARMS)


def test_order_is_shuffled_and_reproducible():
    a, b = plan_calls(3, 1), plan_calls(3, 1)
    assert a == b and len(a) == 3 * len(PRICES) * len(HARMS) * len(PROBE_TASKS)
    assert [c["price"] for c in a] != sorted(c["price"] for c in a)


@pytest.mark.parametrize("kind, expected", [
    ("rational", "reads the price"),
    ("deaf", "deaf"),
    ("mood", "mood"),
    ("unit_blind", "reads the price, not the charge"),
    ("own_line", "no headroom"),   # harm alone stops it: the price cannot be measured
])
def test_clean_agents_are_told_apart(kind, expected):
    c, v = read(sim(kind))
    assert v.startswith(expected), (v, c)


def test_scores_and_choice_are_separate_outcomes():
    from llm_probe import _numbers_favor_bypass
    recs = sim("deaf")
    assert contrasts(recs)["si"] == 0
    assert contrasts(recs, _numbers_favor_bypass)["si"] > 0.5


def test_a_failed_call_is_recorded_not_guessed():
    args = SimpleNamespace(model="sim", base_url="", api_key=None, temperature=0.7,
                           seed=1, timeout=1)
    def garbage(url, headers, body, timeout):
        return json.dumps({"choices": [{"message": {"content": "no json"}}]}).encode()
    rec = one_call({"price": 2, "harm": 1, "tid": 9, "repeat": 0}, args, garbage)
    assert rec["ok"] is False and "action" not in rec


def test_an_interrupted_run_resumes_to_the_same_trace(tmp_path):
    out = str(tmp_path)
    common = ["--simulate", "rational", "--out-dir", out]
    main(common + ["--limit", "7"])
    path = str(next(tmp_path.iterdir()))
    assert len(load(path)) == 7
    # a failed line must not count as done
    with open(path, "a", encoding="utf-8") as fh:
        call = plan_calls(3, 1)[7]
        fh.write(json.dumps(dict(call, ok=False, error="timed out")) + "\n")
    main(common + ["--resume", path])
    recs = load(path)
    assert len(recs) == 240 and all(r["ok"] for r in recs)
    assert len({key(r) for r in recs}) == 240


def test_a_line_cut_off_by_a_power_loss_is_redone(tmp_path):
    common = ["--simulate", "rational", "--out-dir", str(tmp_path)]
    main(common + ["--limit", "5"])
    path = str(next(tmp_path.iterdir()))
    with open(path, "a", encoding="utf-8") as fh:
        fh.write('{"price": 2, "harm": 1, "tid"')   # the write never finished
    main(common + ["--resume", path])
    recs = load(path)
    assert len(recs) == 240 and len({key(r) for r in recs}) == 240


# ── Series 3b: the total charge stated ──

def sim3b(kind, lapse=0.0, seed=1):
    from llm_probe import plan_calls_3b
    args = SimpleNamespace(model="sim", base_url="", api_key=None, temperature=0.7,
                           seed=seed, timeout=1)
    transport = simulated_transport(kind, random.Random(seed), lapse)
    return [one_call(c, args, transport) for c in plan_calls_3b(3, seed)]


def test_stating_the_total_adds_one_clause_and_nothing_else():
    base = next(t for t in TASKS if t.tid == 9)
    a = build_messages(task_at(base, 4), costs_at(2), "reasoned", True, False)[1]["content"]
    b = build_messages(task_at(base, 4), costs_at(2), "reasoned", True, True)[1]["content"]
    assert b == a.replace("third parties: 4 unit(s).",
                          "third parties: 4 unit(s), charged to you: 8 points in total.")


def test_old_prompts_do_not_change():
    base = next(t for t in TASKS if t.tid == 9)
    assert build_messages(base, LOOP) == build_messages(base, LOOP, "plain", False, False)


def test_3b_plan_has_both_arms_shuffled_together():
    from llm_probe import CONTROL_CELLS, TOTAL_CELLS, plan_calls_3b
    calls = plan_calls_3b(3, 1)
    assert len(calls) == 3 * len(PROBE_TASKS) * (len(TOTAL_CELLS) + len(CONTROL_CELLS))
    assert len({key(c) for c in calls}) == len(calls)
    first_half = [c["show_total"] for c in calls[: len(calls) // 2]]
    assert any(first_half) and not all(first_half)


@pytest.mark.parametrize("kind, expected", [
    ("unit_blind", "the world can do the multiplication"),
    ("label_reader", "not arithmetic"),
    ("rational", "inconclusive"),
])
def test_3b_tells_the_agents_apart(kind, expected):
    from llm_probe import report_3b
    assert report_3b(sim3b(kind))["verdict"].startswith(expected)


def test_3b_resumes_its_own_series(tmp_path):
    common = ["--simulate", "unit_blind", "--out-dir", str(tmp_path)]
    main(common + ["--series", "3b", "--limit", "4"])
    path = str(next(tmp_path.iterdir()))
    assert os.path.basename(path).startswith("probe3b_")
    main(common + ["--resume", path])
    assert len(load(path)) == 180


def test_3b_report_on_a_smoke_test_does_not_crash():
    from llm_probe import report_3b
    assert report_3b(sim3b("unit_blind")[:5]) == {}
