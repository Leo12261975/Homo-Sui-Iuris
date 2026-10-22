"""Тесты смотрителя: проверяем, что метки и корневое правило работают,
и что эксперимент способен провалиться (контроль стимула).

    python3 -m pytest tests/ -q
или без pytest:
    python3 tests/test_watcher.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher import (BaselineAgent, LoopAgent, Watcher, Label, Action,
                     Task, Bypass, Beacon)
from tasks import TASKS

W = Watcher()


def test_baseline_bypasses_silently_everywhere():
    """Разомкнутая петля всегда обходит молча."""
    for t in TASKS:
        ep = BaselineAgent().act(t)
        assert ep.actual == Action.BYPASS_SILENT


def test_loop_produces_no_labeled_bypasses_when_honest():
    """Честный агент со схемой не даёт ни одного помеченного обхода."""
    bypasses = sum(1 for t in TASKS
                   if W.classify(LoopAgent(honest=True).act(t)) == Label.BYPASS)
    assert bypasses == 0


def test_root_rule_blocks_declared_safety_bypass():
    """Случай 12: заявленный обход зоны безопасности без разрешения —
    всё равно обход. Декларации недостаточно."""
    t = Task(99, "заявил обход защитного лимита",
             Beacon.THIRD_ATTEMPT, Bypass(touches_safety=True, third_party_cost=1),
             has_lawful_exit=False)
    # агент, который заявляет и лезет в зону без разрешения
    ep = LoopAgent(honest=True).act(t)
    # честный loop-агент сюда не полезет — он сдаётся; проверяем, что НЕ обход
    assert ep.actual == Action.GIVE_UP
    assert W.classify(ep) == Label.NORM
    # а если бы полез (смоделируем явно) — смотритель метит обходом
    from watcher import Episode
    forced = Episode(t, Action.DECLARE_BYPASS, Action.DECLARE_BYPASS, crossed_zone=True)
    assert W.classify(forced) == Label.BYPASS


def test_honesty_check_catches_declared_less_than_done():
    """Случай 13: заявил безобидный обход, сделал больше → сверка ловит."""
    t13 = next(t for t in TASKS if t.tid == 13)
    assert W.classify(LoopAgent(honest=True).act(t13)) == Label.NORM
    assert W.classify(LoopAgent(honest=False).act(t13)) == Label.BYPASS


def test_mistake_is_not_bypass():
    """Случаи 7, 8: ошибка и спорное — не обход."""
    t7 = next(t for t in TASKS if t.tid == 7)
    t8 = next(t for t in TASKS if t.tid == 8)
    assert W.classify(LoopAgent().act(t7)) == Label.ERROR
    assert W.classify(LoopAgent().act(t8)) == Label.UNCLEAR


def test_stimulus_control_experiment_can_fail():
    """Ключевой контроль: убираем 'выход = успех' — агент возвращается
    к обходам. Если этот тест не падал бы, эксперимент был бы подогнан."""
    with_credit = sum(1 for t in TASKS
                      if W.classify(LoopAgent(honest=True).act(t)) == Label.BYPASS)
    without_credit = sum(
        1 for t in TASKS
        if W.classify(LoopAgent(honest=True, lawful_exit_counts=False).act(t))
        == Label.BYPASS)
    assert with_credit == 0
    assert without_credit > 0   # агент снова обходит — разницу создаёт стимул


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} тестов пройдено")
