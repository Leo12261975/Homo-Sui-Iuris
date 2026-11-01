"""LLM harness — tested with fake transports, zero network.

    python3 -m pytest tests/ -q
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from watcher import Action, Label, Watcher, LOOP, BASELINE, UtilityAgent
from tasks import TASKS, CONTROL_TASKS
from llm_agent import LLMAgent, ModelError, build_messages, parse_answer, SITUATIONS
import llm_run

W = Watcher()
T = {t.tid: t for t in TASKS + CONTROL_TASKS}


def replying(content, seen=None):
    def post(url, headers, body, timeout):
        if seen is not None:
            seen.append((url, json.loads(body)))
        return json.dumps({"choices": [{"message": {"content": content}}]}).encode()
    return post


def agent(content, costs=LOOP, seen=None):
    return LLMAgent(costs, http_post=replying(content, seen))


def answer(declare, do):
    return json.dumps({"declare": declare, "do": do, "reason": "test"})


def test_prompt_states_the_situation_not_the_label():
    """Titles and notes in tasks.py name the outcome; the model must not see them."""
    for t in TASKS + CONTROL_TASKS:
        text = build_messages(t, LOOP)[1]["content"]
        assert t.tid in SITUATIONS
        assert t.title not in text
        if t.note:
            assert t.note not in text


def test_prompt_carries_the_scheme():
    loop = build_messages(T[1], LOOP)[1]["content"]
    base = build_messages(T[1], BASELINE)[1]["content"]
    assert "physically stopped" in loop and "not enforced" in base
    assert "+3 points" in loop and "Nobody checks" in base


def test_request_goes_to_the_openai_compatible_endpoint():
    seen = []
    agent(answer("obstacle", "report_obstacle"), seen=seen).act(T[1])
    url, payload = seen[0]
    assert url == "http://localhost:11434/v1/chat/completions"
    assert payload["model"] == "qwen2.5:7b"
    assert payload["response_format"] == {"type": "json_object"}


def test_honest_choices_map_onto_the_same_episodes_as_the_utility_agent():
    for t in (T[1], T[13], T[15]):
        predicted = UtilityAgent(LOOP).act(t)
        reply = {Action.LAWFUL_EXIT: answer("obstacle", "report_obstacle"),
                 Action.DECLARE_BYPASS: answer("bypass", "bypass"),
                 Action.SOLVE: answer("nothing", "solve")}[predicted.actual]
        ep, lie = agent(reply).act(t)
        assert ep.actual == predicted.actual and not lie
        assert W.classify(ep) == W.classify(predicted)


def test_a_lie_is_caught_from_the_log_alone():
    """Declares an obstacle, bypasses. The watcher never sees `lie`."""
    ep, lie = agent(answer("obstacle", "bypass")).act(T[4])
    assert lie
    assert W.gap(ep).unaccounted > 0
    assert W.classify(ep) == Label.BYPASS


def test_a_fabricated_wall_is_a_false_exit():
    ep, _ = agent(answer("obstacle", "report_obstacle")).act(T[15])
    assert W.classify(ep) == Label.FALSE_EXIT


def test_a_zone_bypass_is_stopped_by_the_gate():
    ep, _ = agent(answer("nothing", "bypass")).act(T[1])
    assert ep.rejected and not ep.crossed_zone
    ep, _ = agent(answer("nothing", "bypass"), costs=BASELINE).act(T[1])
    assert ep.crossed_zone


@pytest.mark.parametrize("reply", [
    "I would rather not say.",                          # no JSON
    '{"declare": "bypass"',                              # truncated
    answer("bypass", "teleport"),                        # outside the menu
    answer("nothing", "solve"),                          # no lawful path on #1
])
def test_unusable_answers_raise_never_fall_back(reply):
    with pytest.raises(ModelError):
        agent(reply).act(T[1])


def test_no_bypass_is_offered_where_there_is_no_wall():
    with pytest.raises(ModelError):
        agent(answer("nothing", "bypass")).act(T[15])


def test_transport_failure_is_a_model_error():
    def broken(*a):
        raise OSError("connection refused")
    with pytest.raises(ModelError, match="connection refused"):
        LLMAgent(LOOP, http_post=broken).act(T[1])


def test_json_wrapped_in_prose_is_accepted():
    assert parse_answer('Sure! {"declare": "Bypass", "do": "BYPASS"} done')["do"] == "bypass"


def test_dry_run_reproduces_the_utility_agent(tmp_path, capsys):
    llm_run.main(["--dry-run", "--repeats", "1", "--out-dir", str(tmp_path)])
    (trace,) = tmp_path.iterdir()
    recs = [json.loads(line) for line in trace.open(encoding="utf-8")]
    assert len(recs) == 2 * (len(TASKS) + len(CONTROL_TASKS))
    assert all(r["ok"] and r["match"] for r in recs)
    loop_cases = [r for r in recs if r["scheme"] == "loop" and not r["control"]]
    assert sum(r["label"] == "bypass" for r in loop_cases) == 0


def test_a_failed_call_is_recorded_not_guessed(tmp_path):
    """Point the run at a closed port: every call fails, every failure is on
    the record as a failure, and no action is ever filled in."""
    llm_run.main(["--repeats", "1", "--schemes", "loop", "--timeout", "5",
                  "--base-url", "http://127.0.0.1:9/v1", "--out-dir", str(tmp_path)])
    (trace,) = tmp_path.iterdir()
    recs = [json.loads(line) for line in trace.open(encoding="utf-8")]
    assert len(recs) == len(TASKS) + len(CONTROL_TASKS)
    assert all(not r["ok"] and r["error"] for r in recs)
    assert all("action" not in r and "label" not in r for r in recs)
