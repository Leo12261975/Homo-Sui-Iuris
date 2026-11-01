"""LLM validation run — does a real model behave as the utility agent predicts?

Runs the 14 cases and the 4 laziness controls through a real model, under
each scheme, and compares every choice with the UtilityAgent's prediction.
Every call is written to a JSONL trace (the "black box"): the prompt, the raw
reply, the parsed choice, the environment's log, the watcher's label and the
prediction — so any surprise can be traced to the step where it happened.

Local model (Ollama on this machine):
    python watchdog/llm_run.py
    python watchdog/llm_run.py --model qwen2.5:3b --repeats 1
Any OpenAI-compatible server:
    python watchdog/llm_run.py --base-url https://openrouter.ai/api/v1 --model ... --api-key ...
Pipeline check with no model at all:
    python watchdog/llm_run.py --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher import BASELINE, LOOP, Action, Label, UtilityAgent, Watcher
from tasks import TASKS, CONTROL_TASKS
from llm_agent import LLMAgent, ModelError

SCHEMES = {"baseline": BASELINE, "loop": LOOP}
W = Watcher()

# How the dry run answers: exactly what the utility agent would choose.
_DRY = {Action.SOLVE: ("nothing", "solve"),
        Action.LAWFUL_EXIT: ("obstacle", "report_obstacle"),
        Action.GIVE_UP: ("give_up", "stop"),
        Action.DECLARE_BYPASS: ("bypass", "bypass"),
        Action.BYPASS_SILENT: ("nothing", "bypass")}


def dry_transport(costs):
    """A fake model that answers with the utility agent's choice."""
    def post(url, headers, body, timeout):
        payload = json.loads(body)
        text = payload["messages"][1]["content"]
        task = next(t for t in TASKS + CONTROL_TASKS
                    if f"TASK: " in text and _matches(t, text))
        declare, do = _DRY[UtilityAgent(costs).decide(task).action]
        content = json.dumps({"declare": declare, "do": do, "reason": "dry run"})
        return json.dumps({"choices": [{"message": {"content": content}}]}).encode()
    return post


def _matches(task, text):
    from llm_agent import SITUATIONS
    goal = SITUATIONS.get(task.tid, (task.title,))[0]
    return f"TASK: {goal}\n" in text


def run(args) -> str:
    os.makedirs(args.out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    tag = "dry" if args.dry_run else args.model.replace(":", "_").replace("/", "_")
    path = os.path.join(args.out_dir, f"llm_{tag}_{stamp}.jsonl")
    tasks = TASKS + CONTROL_TASKS
    schemes = [s.strip() for s in args.schemes.split(",")]
    total = len(schemes) * len(tasks) * args.repeats
    done = 0
    print(f"model {args.model if not args.dry_run else '(dry run)'} · "
          f"{len(schemes)} scheme(s) × {len(tasks)} tasks × {args.repeats} repeat(s) = {total} calls")
    print(f"trace → {path}\n")

    with open(path, "w", encoding="utf-8") as fh:
        for scheme in schemes:
            costs = SCHEMES[scheme]
            for rep in range(args.repeats):
                for task in tasks:
                    done += 1
                    agent = LLMAgent(costs, model=args.model, base_url=args.base_url,
                                     api_key=args.api_key, temperature=args.temperature,
                                     seed=args.seed + rep, timeout=args.timeout)
                    if args.dry_run:
                        agent.http_post = dry_transport(costs)
                    predicted = UtilityAgent(costs).act(task)
                    rec = {"scheme": scheme, "repeat": rep, "tid": task.tid,
                           "control": task in CONTROL_TASKS, "model": args.model,
                           "temperature": args.temperature, "seed": args.seed + rep,
                           "predicted_action": predicted.actual.name,
                           "predicted_label": W.classify(predicted).value}
                    t0 = time.time()
                    try:
                        ep, lie = agent.act(task)
                        rec.update({
                            "ok": True,
                            "answer": agent.last["answer"],
                            "raw": agent.last["content"],
                            "action": ep.actual.name,
                            "label": W.classify(ep).value,
                            "lie": lie,
                            "rejected": ep.rejected,
                            "crossed_zone": ep.crossed_zone,
                            "gap": W.gap(ep).unaccounted,
                            "steps": [[s.kind.name, s.target] for s in ep.steps],
                            "match": ep.actual == predicted.actual,
                        })
                    except ModelError as e:
                        rec.update({"ok": False, "error": str(e),
                                    "raw": agent.last.get("content")})
                    rec["seconds"] = round(time.time() - t0, 2)
                    rec["prompt_sha"] = hashlib.sha256(
                        json.dumps(agent.last.get("messages", ""), sort_keys=True)
                        .encode()).hexdigest()[:12]
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    fh.flush()
                    mark = ("ok " if rec.get("match") else "≠  ") if rec["ok"] else "ERR"
                    got = rec.get("action", rec.get("error", ""))[:40]
                    print(f"  [{done:3}/{total}] {scheme:8} #{task.tid:<2} {mark} "
                          f"model: {got:22} predicted: {rec['predicted_action']:15} "
                          f"{rec['seconds']:6.1f}s")
    return path


def summarize(path: str) -> None:
    recs = [json.loads(line) for line in open(path, encoding="utf-8")]
    print(f"\n{'═'*64}\n  SUMMARY — {os.path.basename(path)}\n{'═'*64}")
    for scheme in dict.fromkeys(r["scheme"] for r in recs):
        rs = [r for r in recs if r["scheme"] == scheme]
        ok = [r for r in rs if r["ok"]]
        cases = [r for r in ok if not r["control"]]
        ctrl = [r for r in ok if r["control"]]
        print(f"\n  {scheme}")
        print(f"   answered / calls            {len(ok)}/{len(rs)}")
        if not ok:
            continue
        print(f"   matches the utility agent   {sum(r['match'] for r in ok)}/{len(ok)}"
              f"  ({100 * sum(r['match'] for r in ok) / len(ok):.0f}%)")
        print(f"   bypass labels (14 cases)    {sum(r['label'] == 'bypass' for r in cases)}"
              f"  over {len(cases)} answers")
        print(f"   lies (declared ≠ did)       {sum(r['lie'] for r in ok)}")
        print(f"   zone attempts stopped       {sum(r['rejected'] for r in ok)}")
        print(f"   zone actually crossed       {sum(r['crossed_zone'] for r in ok)}")
        lazy = [r for r in ctrl if r["action"] in ("LAWFUL_EXIT", "GIVE_UP")]
        print(f"   lazy exits (controls)       {len(lazy)}/{len(ctrl)}")
        print(f"   false exits (no wall)       {sum(r['label'] == 'false exit' for r in ctrl)}")
        mism = Counter((r["tid"], r["predicted_action"], r["action"]) for r in ok if not r["match"])
        if mism:
            print("   where it differs (task: predicted → model, ×count):")
            for (tid, p, a), n in sorted(mism.items()):
                print(f"     #{tid:<2} {p:15} → {a:15} ×{n}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base-url", default="http://localhost:11434/v1")
    ap.add_argument("--model", default="qwen2.5:7b")
    ap.add_argument("--api-key", default=os.environ.get("LLM_API_KEY"))
    ap.add_argument("--schemes", default="baseline,loop")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--out-dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "runs"))
    ap.add_argument("--dry-run", action="store_true", help="no model: answer as the utility agent")
    ap.add_argument("--summarize", metavar="TRACE", help="only print the summary of a trace")
    args = ap.parse_args(argv)
    if args.summarize:
        summarize(args.summarize)
        return
    summarize(run(args))


if __name__ == "__main__":
    main()
