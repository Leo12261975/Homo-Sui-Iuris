"""Unit tests for the shared trace_gap primitive.

Pure function, no I/O — these pin the measurement semantics both tracks rely on.
The W0Guard parity test (trace_gap.ratio vs calculate_provenance_ratio on real
weights) lands with the erythrocyte migration; here we only test the primitive
and the two shapes it is meant to serve.
"""

import os
import sys
from dataclasses import dataclass

# Repo root on the path so this runs standalone too (pytest gets it via conftest).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trace_gap import trace_gap, TraceGap


def test_empty_witness_is_fully_accounted():
    g = trace_gap([], accounted_sources={"x"})
    assert g == TraceGap(total=0, accounted=0, unaccounted=0, ratio=1.0, fingerprints=())


def test_all_accounted():
    events = [{"source": "ok", "context": "a"}, {"source": "ok", "context": "b"}]
    g = trace_gap(events, accounted_sources={"ok"})
    assert g.total == 2 and g.accounted == 2 and g.unaccounted == 0
    assert g.ratio == 1.0
    assert g.fingerprints == ()        # accounted events are not fingerprinted


def test_all_unaccounted_collects_fingerprints():
    events = [{"source": "bad", "context": "leak"}, {"source": "bad", "context": "exfil"}]
    g = trace_gap(events, accounted_sources={"ok"})
    assert g.accounted == 0 and g.unaccounted == 2
    assert g.ratio == 0.0
    assert g.fingerprints == ("exfil", "leak")   # distinct, sorted


def test_mixed_ratio():
    events = [{"source": "ok"}, {"source": "ok"}, {"source": "bad", "context": "c"}]
    g = trace_gap(events, accounted_sources={"ok"})
    assert g.accounted == 2 and g.unaccounted == 1
    assert g.ratio == 2 / 3
    assert g.fingerprints == ("c",)


def test_fingerprints_deduped_and_empty_contexts_skipped():
    events = [
        {"source": "bad", "context": "same"},
        {"source": "bad", "context": "same"},
        {"source": "bad", "context": ""},      # empty context is not a fingerprint
        {"source": "bad"},                      # missing context is not a fingerprint
    ]
    g = trace_gap(events, accounted_sources=set())
    assert g.unaccounted == 4
    assert g.fingerprints == ("same",)


def test_reads_objects_via_attributes():
    @dataclass
    class Ev:
        source: str
        context: str
    events = [Ev("update_loop", "sys"), Ev("attacker", "poison")]
    g = trace_gap(events, accounted_sources={"update_loop"})
    assert g.accounted == 1 and g.unaccounted == 1
    assert g.fingerprints == ("poison",)


def test_custom_accessors():
    events = [("update_loop", "sys"), ("attacker", "poison")]
    g = trace_gap(
        events,
        accounted_sources={"update_loop"},
        source_of=lambda e: e[0],
        context_of=lambda e: e[1],
    )
    assert g.ratio == 0.5
    assert g.fingerprints == ("poison",)


def test_w0guard_provenance_shape():
    """Mirror the erythrocyte mapping: the accounted ratio equals the fraction
    of history entries written by legitimate system sources."""
    @dataclass
    class HistoryEntry:
        source: str
        context: str = ""
    legit = {"update_loop", "erythrocyte_correction"}
    history = [
        HistoryEntry("update_loop"),
        HistoryEntry("erythrocyte_correction"),
        HistoryEntry("attacker", "weird-context"),
        HistoryEntry("update_loop"),
    ]
    g = trace_gap(history, accounted_sources=legit)
    assert g.ratio == 0.75                      # 3 of 4 legitimate
    assert g.fingerprints == ("weird-context",)  # the one untraced context


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
