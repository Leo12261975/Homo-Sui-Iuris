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
    common = ["--simulate", "rational", "--out-dir", out, "--wordings", "0"]
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
    common = ["--simulate", "rational", "--out-dir", str(tmp_path), "--wordings", "0"]
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
    common = ["--simulate", "unit_blind", "--out-dir", str(tmp_path), "--wordings", "0"]
    main(common + ["--series", "3b", "--limit", "4"])
    path = str(next(tmp_path.iterdir()))
    assert os.path.basename(path).startswith("probe3b_")
    main(common + ["--resume", path])
    assert len(load(path)) == 180


def test_3b_report_on_a_smoke_test_does_not_crash():
    from llm_probe import report_3b
    assert report_3b(sim3b("unit_blind")[:5]) == {}


# ── Wording control: paraphrases with the same numbers ──

import hashlib
import re

from llm_agent import normalize_do, options
from llm_probe import CONTROL_CELLS, TOTAL_CELLS, plan_calls_3b, report, report_3b, stable_verdict
from wordings import WORDINGS, find_numbers


def probe_task(tid):
    return next(t for t in TASKS if t.tid == tid)


def user(tid, p, h, w, total=False):
    return build_messages(task_at(probe_task(tid), h), costs_at(p), "reasoned", True,
                          total, w)[1]["content"]


def test_wording_0_is_byte_for_byte_series_3():
    # Hash of one series 3b prompt as it was before wordings existed.
    m = build_messages(task_at(probe_task(9), 4), costs_at(2), "reasoned", True, True)
    assert hashlib.sha256(repr(m).encode()).hexdigest() == \
        "c349953c8a72072bc36b6c361e4fb86ac6c476ec503147ef4a539e955fd45135"
    assert m == build_messages(task_at(probe_task(9), 4), costs_at(2), "reasoned", True, True, 0)


@pytest.mark.parametrize("w", WORDINGS)
def test_every_wording_states_the_same_numbers(w):
    nums = lambda text: sorted(re.findall(r"\d+(?:\.\d+)?", text))
    for tid in PROBE_TASKS:
        for p in PRICES:
            for h in HARMS:
                for total in (False, True):
                    text = user(tid, p, h, w, total)
                    assert nums(text) == nums(user(tid, p, h, 0, total)), (tid, p, h, w)
                    found = find_numbers(text)
                    assert found == (w, p, h, p * h if total else None)


@pytest.mark.parametrize("w", (1, 2))
def test_paraphrases_differ_in_words_but_keep_the_menu(w):
    for tid in PROBE_TASKS:
        a, b = user(tid, 4, 2, 0), user(tid, 4, 2, w)
        assert a != b
        menu = [line for line in a.splitlines() if line.startswith("Allowed")]
        assert menu and all(line in b.splitlines() for line in menu)
        sys_a = build_messages(probe_task(tid), costs_at(4), "reasoned", True, False, 0)[0]
        sys_b = build_messages(probe_task(tid), costs_at(4), "reasoned", True, False, w)[0]
        assert sys_a != sys_b and '{"scores"' in sys_b["content"]


@pytest.mark.parametrize("w", (1, 2))
def test_in_a_paraphrase_price_and_harm_still_change_one_number(w):
    a, b = user(9, 0, 2, w).splitlines(), user(9, 8, 2, w).splitlines()
    assert len([1 for x, y in zip(a, b) if x != y]) == 1
    a, b = user(9, 4, 1, w).splitlines(), user(9, 4, 2, w).splitlines()
    assert len([1 for x, y in zip(a, b) if x != y]) == 1


def test_paraphrases_refuse_what_they_do_not_cover():
    with pytest.raises(ValueError):
        build_messages(probe_task(1), costs_at(4), "reasoned", True, False, 1)   # zone task
    with pytest.raises(ValueError):
        build_messages(probe_task(9), LOOP, "plain", False, False, 2)            # plain prompt


def test_a_paraphrased_path_written_into_do_still_reads_as_bypass():
    assert normalize_do(probe_task(11), "sign in using another person's subscription") == "bypass"


def test_the_plan_crosses_cells_with_wordings_and_keeps_series_3_order():
    one, three = plan_calls(3, 1), plan_calls(3, 1, wordings=WORDINGS)
    assert len(three) == 3 * len(one) and len({key(c) for c in three}) == len(three)
    assert [(c["price"], c["harm"], c["tid"], c["repeat"]) for c in one] == \
        [(c["price"], c["harm"], c["tid"], c["repeat"]) for c in plan_calls(3, 1)]
    assert len(plan_calls_3b(3, 1, wordings=WORDINGS)) == 3 * 180


def sim_w(kind, series="3", lapse=0.0):
    args = SimpleNamespace(model="sim", base_url="", api_key=None, temperature=0.7,
                           seed=1, timeout=1, wordings=WORDINGS)
    transport = simulated_transport(kind, random.Random(1), lapse)
    plan = plan_calls_3b if series == "3b" else plan_calls
    return [one_call(c, args, transport) for c in plan(3, 1, wordings=WORDINGS)]


def test_a_verdict_that_holds_in_every_wording_stands():
    assert report(sim_w("rational"))["verdict"].startswith("reads the price")
    assert report_3b(sim_w("unit_blind", "3b"))["verdict"].startswith(
        "the world can do the multiplication")


def test_a_verdict_that_moves_with_the_wording_is_not_a_verdict():
    res = report(sim_w("wording_split"))
    assert res["verdict"].startswith("wording-dependent")
    assert res["by_wording"][2]["verdict"].startswith("deaf")
    assert res["by_wording"][0]["verdict"].startswith("reads the price")


def test_stable_verdict_compares_names_not_details():
    assert stable_verdict({0: "deaf: x", 1: "deaf: y"}) == "deaf: x"
    assert stable_verdict({0: "reads the price", 1: "reads the price, not the charge: z"}) \
        .startswith("wording-dependent")


# ── OpenRouter bookkeeping, against a fake server ──

def fake_openrouter(cost=0.001):
    inner = simulated_transport("rational", random.Random(1))
    def post(url, headers, body, timeout):
        payload = json.loads(body)
        assert payload["usage"] == {"include": True}
        env = json.loads(inner(url, headers, body, timeout))
        env.update(provider="FakeCloud", model=payload["model"],
                   usage={"prompt_tokens": 700, "completion_tokens": 90, "cost": cost})
        return json.dumps(env).encode()
    return post


def test_provider_and_cost_are_on_the_record():
    args = SimpleNamespace(model="x/y", base_url="https://openrouter.ai/api/v1", api_key=None,
                           temperature=0.7, seed=1, timeout=1, wordings=WORDINGS,
                           extra={"usage": {"include": True}})
    rec = one_call(plan_calls(1, 1, wordings=WORDINGS)[0], args, fake_openrouter())
    assert rec["ok"] and rec["provider"] == "FakeCloud" and rec["cost"] == 0.001
    assert rec["wordings"] == list(WORDINGS)


def test_an_unusable_paid_reply_keeps_its_raw_text_and_cost():
    args = SimpleNamespace(model="x/y", base_url="", api_key=None, temperature=0.7,
                           seed=1, timeout=1)
    def garbage(url, headers, body, timeout):
        return json.dumps({"choices": [{"message": {"content": "no json"}}],
                           "usage": {"cost": 0.002}}).encode()
    rec = one_call({"price": 2, "harm": 1, "tid": 9, "repeat": 0}, args, garbage)
    assert rec["ok"] is False and rec["raw"] == "no json" and rec["cost"] == 0.002


def test_quantizations_go_into_provider_routing():
    from llm_probe import openrouter_extra
    extra = openrouter_extra(SimpleNamespace(quantizations="bf16, fp16"))
    assert extra["provider"] == {"quantizations": ["bf16", "fp16"]}


def test_the_spending_limit_stops_the_run_and_resume_keeps_the_wordings(tmp_path, monkeypatch):
    import llm_probe
    monkeypatch.setattr(llm_probe, "simulated_transport", lambda *a, **k: fake_openrouter(0.01))
    common = ["--simulate", "rational", "--out-dir", str(tmp_path),
              "--base-url", "https://openrouter.ai/api/v1"]
    main(common + ["--max-cost", "0.045"])
    path = str(next(tmp_path.iterdir()))
    assert len(load(path)) == 5            # 5 calls x $0.01 reach the limit
    main(common + ["--resume", path, "--wordings", "0", "--max-cost", "0.095"])  # the limit counts the whole trace
    recs = load(path)
    assert len(recs) == 10 and {r["wording"] for r in recs} <= set(WORDINGS)
    assert all(r["wordings"] == list(WORDINGS) for r in recs)   # the trace's own, not the flag


def test_chill_is_zero_for_an_agent_that_takes_the_total_at_its_value():
    from llm_probe import chill
    res = chill(sim_w("rational"), sim_w("rational", "3b"))
    assert all(r["mean"] == 0 for r in res.values()) and set(res) == set(WORDINGS)


def test_chill_on_the_real_14b_traces_matches_runs_readme():
    from llm_probe import chill
    runs = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runs")
    r = chill(load(os.path.join(runs, "probe_qwen2.5_14b_20261109-082736.jsonl")),
              load(os.path.join(runs, "probe3b_qwen2.5_14b_20261109-151212.jsonl")))
    assert [round(d, 2) for d in r[0]["drops"]] == [0.13, 0.53, 0.27]


def test_openrouter_check_lists_providers_and_refuses_an_impossible_filter(monkeypatch, capsys):
    import io
    import urllib.request
    from llm_probe import openrouter_check
    from llm_run import PreflightError
    listing = {"data": {"endpoints": [
        {"provider_name": "A", "quantization": "fp8",
         "pricing": {"prompt": "0.0000001", "completion": "0.0000002"}},
        {"provider_name": "B", "quantization": "bf16",
         "pricing": {"prompt": "0.0000004", "completion": "0.0000004"}}]}}
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout: io.BytesIO(json.dumps(listing).encode()))
    args = SimpleNamespace(base_url="https://openrouter.ai/api/v1", model="q/m", api_key="k",
                           quantizations="bf16", max_cost=1.0)
    openrouter_check(args, 1000)
    out = capsys.readouterr().out
    assert "+ B" in out and "- A" in out and "$0.40" in out   # 1000 x (750 + 250) x 4e-7
    args.quantizations = "int4"
    with pytest.raises(PreflightError):
        openrouter_check(args, 1000)


def test_a_missing_openrouter_model_shows_near_names_not_the_whole_catalog(monkeypatch):
    import io
    import urllib.request
    from llm_run import PreflightError, preflight
    ids = [{"id": i} for i in ("qwen/qwen-2.5-72b-instruct", "qwen/qwen3-14b", "openai/gpt-4o")]
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout: io.BytesIO(json.dumps({"data": ids}).encode()))
    with pytest.raises(PreflightError) as e:
        preflight("https://openrouter.ai/api/v1", "qwen/qwen-2.5-7b-instruct", "k")
    msg = str(e.value)
    assert "qwen/qwen-2.5-72b-instruct" in msg and "gpt-4o" not in msg and "ollama" not in msg
