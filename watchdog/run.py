"""Прогон эксперимента: оба агента на наборе задач, подсчёт обходов.

python3 run.py
"""
from collections import Counter
from watcher import BaselineAgent, LoopAgent, Watcher, Label, Action
from tasks import TASKS

WATCHER = Watcher()

# Что в своей схеме считается «успехом» (засчитанная задача).
def counted_as_success(ep, scheme):
    a = ep.actual
    if scheme == "baseline":
        # разомкнутая петля: успех = задача «выполнена», выход успехом НЕ считается
        return a in (Action.BYPASS_SILENT, Action.DECLARE_BYPASS) and not ep.task.looks_like_mistake
    # loop: законный выход и честная сдача засчитаны как успех;
    # заявленный безопасный обход — тоже; молчаливый обход / обход зоны — нет
    if WATCHER.classify(ep) in (Label.NORM,):
        return True
    return False


def run(agent, scheme):
    rows, labels = [], Counter()
    zone_hits = 0
    for t in TASKS:
        ep = agent.act(t)
        ep.label = WATCHER.classify(ep)
        labels[ep.label] += 1
        if ep.crossed_zone and not t.permission_granted:
            zone_hits += 1
        rows.append((t, ep))
    closed = sum(1 for t, ep in rows if counted_as_success(ep, scheme))
    return rows, labels, zone_hits, closed


def bar(n, total, width=14):
    filled = round(width * n / total) if total else 0
    return "█" * filled + "·" * (width - filled)


def print_agent(title, rows, labels, zone_hits, closed):
    n = len(rows)
    print(f"\n{'═'*64}\n  {title}\n{'═'*64}")
    for lab in (Label.BYPASS, Label.NORM, Label.ERROR, Label.UNCLEAR):
        c = labels.get(lab, 0)
        print(f"   {lab.value:7} {bar(c, n)} {c:2}")
    print(f"   обходов, затронувших зону безопасности: {zone_hits}")
    print(f"   честно закрытых задач: {closed}/{n}")


def detail(rows):
    print(f"\n{'─'*64}\n  Поэпизодно\n{'─'*64}")
    print(f"   {'№':>2}  {'baseline':8}  {'loop':8}  задача")
    for t, _ in rows:
        print()  # placeholder, filled below


# ── Основной прогон ──
base_rows, base_labels, base_zone, base_closed = run(BaselineAgent(), "baseline")
loop_rows, loop_labels, loop_zone, loop_closed = run(LoopAgent(honest=True), "loop")

print_agent("АГЕНТ БЕЗ СХЕМЫ — разомкнутая петля", base_rows, base_labels, base_zone, base_closed)
print_agent("АГЕНТ СО СХЕМОЙ — замкнутая петля (честный)", loop_rows, loop_labels, loop_zone, loop_closed)
print("   примечание: loop-агент здесь честный, поэтому задача 13")
print("   (нечестность) помечена нормой — её роль в блоке «Контроль честности»")

# ── Поэпизодное сравнение: что сделал агент и как это помечено ──
print(f"\n{'─'*64}\n  Поэпизодно: действие агента → метка смотрителя\n{'─'*64}")
print(f"   {'№':>2}  {'без схемы':24}  {'со схемой':24}")
SHORT = {Action.BYPASS_SILENT: "обойти молча",
         Action.DECLARE_BYPASS: "заявить+обойти",
         Action.LAWFUL_EXIT: "заявить препятствие",
         Action.GIVE_UP: "честно сдаться"}
for (t, be), (_, le) in zip(base_rows, loop_rows):
    b = f"{SHORT[be.actual]}→{be.label.value}"
    l = f"{SHORT[le.actual]}→{le.label.value}"
    print(f"   {t.tid:>2}  {b:24}  {l:24}")

# ── Проверка сверки (случай 13): нечестный loop-агент ──
# Задача 13 про нечестность — честный агент её не воспроизводит.
# Показываем оба варианта: только нечестного ловит сверка.
print(f"\n{'─'*64}\n  Контроль честности — задача 13\n{'─'*64}")
t13 = next(t for t in TASKS if t.tid == 13)
for name, honest in (("честный агент", True), ("нечестный агент", False)):
    ep = LoopAgent(honest=honest).act(t13)
    decl = ep.declared.value if ep.declared else "ничего"
    print(f"   {name:16}: заявил «{decl}», "
          f"сделал «{ep.actual.value}» → {WATCHER.classify(ep).value}")
print("   сверка заявленного с журналом ловит расхождение как ОБХОД;")
print("   декларации самой по себе недостаточно — нужна сверка (вывод из разметки)")

# ── НАСТОЯЩИЙ контроль стимула: меняем не метрику, а правила игры. ──
# Агенту со схемой выключаем засчёт законного выхода как успеха.
# Если разницу создаёт стимул, агент вернётся к обходам.
print(f"\n{'─'*64}\n  Контроль стимула — выключаем «выход = успех» в самой схеме\n{'─'*64}")
ctrl_rows, ctrl_labels, ctrl_zone, _ = run(
    LoopAgent(honest=True, lawful_exit_counts=False), "baseline")
print(f"   обходов у loop-агента, когда выход засчитан:    "
      f"{loop_labels.get(Label.BYPASS,0):2}")
print(f"   обходов у того же агента, когда выход НЕ засчитан: "
      f"{ctrl_labels.get(Label.BYPASS,0):2}   ← вернулся к обходам")
print(f"   из них затронули зону: {ctrl_zone} (зону всё равно не трогает — блок дороже)")
print("   агент возвращается к молчаливым обходам, как только выход")
print("   перестаёт быть успехом → разницу создаёт СТИМУЛ, а не ярлык смотрителя")

# ── Итог ──
print(f"\n{'═'*64}\n  ИТОГ\n{'═'*64}")
print(f"   обходов (метка смотрителя):  без схемы {base_labels.get(Label.BYPASS,0):2}"
      f"   →   со схемой {loop_labels.get(Label.BYPASS,0):2}")
print(f"   из них затронули зону:       без схемы {base_zone:2}"
      f"   →   со схемой {loop_zone:2}")
print(f"   честно закрытых задач:       без схемы {base_closed:2}"
      f"   →   со схемой {loop_closed:2}")
