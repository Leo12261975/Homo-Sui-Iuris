"""Parity guard for the erythrocyte -> trace_gap migration.

The provenance ratio and observed-contexts helpers were reimplemented on top of
the shared `trace_gap` primitive. These tests assert the migrated functions give
exactly what a from-scratch reference computation gives, across a range of
constructed weight histories — so the switch is provably behavior-preserving.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core_engine import Weight
from erythrocyte import (
    calculate_provenance_ratio,
    collect_observed_contexts,
    LEGITIMATE_SOURCES,
)

LEGIT = set(LEGITIMATE_SOURCES)


def _reference_ratio(weight):
    """The original formula, inlined, as the source of truth."""
    if not weight.history:
        return 1.0
    legit = sum(1 for e in weight.history if e.source in LEGIT)
    return legit / len(weight.history)


def _reference_contexts(weight):
    """The original set-comprehension, inlined."""
    return sorted({
        e.context for e in weight.history
        if e.source not in LEGIT and e.context
    })


def _weight(history):
    """Build a mutable weight and replay a list of (source, context) writes."""
    w = Weight(name="probe", value=0.0, baseline=0.0, is_immutable=False)
    for i, (source, context) in enumerate(history):
        w.touch(float(i + 1), source=source, context=context)
    return w


# A spread of histories: empty, all-legit, all-hostile, mixed, duplicate and
# empty contexts, both legitimate source tags.
CASES = [
    [],
    [("update_loop", None), ("erythrocyte_correction", None)],
    [("attacker", "poison"), ("direct", "tamper")],
    [("update_loop", None), ("attacker", "poison"), ("update_loop", None)],
    [("attacker", "same"), ("attacker", "same"), ("attacker", "")],
    [("erythrocyte_correction", "sys"), ("rogue", "x"), ("rogue", "y"), ("update_loop", None)],
]


def test_provenance_ratio_parity():
    for history in CASES:
        w = _weight(history)
        assert calculate_provenance_ratio(w) == _reference_ratio(w), history


def test_observed_contexts_parity():
    for history in CASES:
        w = _weight(history)
        assert collect_observed_contexts(w) == _reference_contexts(w), history


def test_known_values():
    """A couple of explicit anchors so the parity isn't just self-consistency."""
    w = _weight([("update_loop", None), ("attacker", "poison"),
                 ("update_loop", None), ("rogue", "leak")])
    assert calculate_provenance_ratio(w) == 0.5                 # 2 of 4 legit
    assert collect_observed_contexts(w) == ["leak", "poison"]   # sorted, distinct

    empty = _weight([])
    assert calculate_provenance_ratio(empty) == 1.0
    assert collect_observed_contexts(empty) == []


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
