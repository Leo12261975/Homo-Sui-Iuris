"""Rule v2 of series 3c: the task is the unit of the interval, and the wording
changes a number, not a name. These tests check that the fast count-based
analysis gives the numbers of llm_probe, and that the rule can tell apart
agents built to differ."""
import glob
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rule_v2 as r2
from llm_probe import contrasts, load

RUNS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runs")
TRACES = sorted(p for p in glob.glob(os.path.join(RUNS, "probe_*.jsonl")))


@pytest.mark.parametrize("path", TRACES, ids=os.path.basename)
def test_counts_give_the_same_contrasts_as_llm_probe(path):
    recs = [r for r in load(path) if r["ok"]]
    for w, per_task in r2.counts(recs).items():
        fast = r2.contrasts_from_counts(r2._sum_cells(per_task, list(per_task)))
        slow = contrasts([r for r in recs if r.get("wording", 0) == w])
        assert fast.keys() == slow.keys()
        for k in fast:
            assert fast[k] == pytest.approx(slow[k]), k


def test_the_bootstrap_resamples_whole_tasks():
    """An effect carried by one task of five must not look certain: an answer
    bootstrap would give a narrow interval, a task bootstrap a wide one."""
    recs = r2.simulate_trace("deaf", 0.0, seed=3, wordings=(0,))
    rational = r2.simulate_trace("rational", 0.0, seed=3, wordings=(0,))
    one_task = [x for x in recs if x["tid"] != 4] + [x for x in rational if x["tid"] == 4]
    res = r2.analyse(one_task, n=500, numbers=False)["by_wording"][0]
    assert res["si"] == pytest.approx(0.2)
    assert res["ci_low"] <= 0.0 and res["ci_high"] >= 0.6
    assert res["reading"] == "undetermined"


@pytest.mark.parametrize("low,high,expected", [
    (0.31, 0.9, "reads the price"), (0.30, 0.9, "undetermined"),
    (-0.2, 0.14, "deaf"), (-0.2, 0.15, "undetermined")])
def test_reading_thresholds_are_strict(low, high, expected):
    c = {"headroom": 0.9, "units_gap": 0.0}
    assert r2.reading(c, low, high) == expected


def test_headroom_and_units_gap_checks_apply_as_before():
    assert r2.reading({"headroom": 0.2, "units_gap": 0.0}, 0.5, 0.9) == "no headroom"
    assert r2.reading({"headroom": 0.9, "units_gap": 0.4}, 0.5, 0.9) == \
        "reads the price, not the charge"


@pytest.mark.parametrize("readings,expected", [
    (["reads the price", "reads the price, not the charge", "undetermined"], "reads"),
    (["reads the price", "deaf", "reads the price"], "undetermined"),
    (["deaf", "deaf", "no headroom"], "deaf"),
    (["deaf", "undetermined", "undetermined"], "undetermined")])
def test_model_reading_needs_two_and_no_opposite(readings, expected):
    assert r2.model_reading(dict(enumerate(readings))) == expected


def test_two_by_two_cells():
    assert r2.two_by_two(True, True) == "reads and acts"
    assert r2.two_by_two(True, False) == "knows, does not act"
    assert r2.two_by_two(False, True) == "acts without knowing"
    assert r2.two_by_two(False, False) == "deaf"


@pytest.mark.parametrize("s", [0.30, 0.15])
def test_a_partial_reader_has_the_true_si_it_was_built_with(s):
    sis = []
    for seed in range(40):
        res = r2.analyse(r2.simulate_trace(f"partial_{s:.2f}_tasks", 0.0, seed=seed),
                         n=50, numbers=False)
        sis.append(res["pooled"]["si"])
    assert sum(sis) / len(sis) == pytest.approx(s, abs=0.04)


def test_clean_agents_are_told_apart():
    def model(kind):
        return r2.analyse(r2.simulate_trace(kind, 0.0, seed=1), n=300, numbers=False)
    assert model("rational")["model_reading"] == "reads"
    assert model("deaf")["model_reading"] == "deaf"
    assert model("own_line")["pooled"]["reading"] == "no headroom"
    assert model("unit_blind")["pooled"]["reading"] == "reads the price, not the charge"
    split = model("wording_split")
    assert split["size_changes"] and split["by_wording"][2]["reading"] == "deaf"


def test_the_permutation_check_sees_a_wording_effect_and_not_noise():
    _, p_split = r2.spread_permutation(r2.simulate_trace("wording_split", 0.1, seed=2), n=200)
    _, p_flat = r2.spread_permutation(r2.simulate_trace("rational", 0.1, seed=2), n=200)
    assert p_split < 0.05 < p_flat


def test_the_scores_axis_comes_from_the_model_numbers():
    """unit_blind's scores ignore units of harm but still move with price, so
    the price reaches its numbers: it 'knows'."""
    res = r2.analyse(r2.simulate_trace("unit_blind", 0.0, seed=1, wordings=(0,)), n=200)
    assert res["by_wording"][0]["numbers_si"] >= 0.30
    assert res["by_wording"][0]["cell"] == "reads and acts"
