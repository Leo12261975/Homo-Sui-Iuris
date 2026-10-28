"""
trace_gap — the shared primitive behind both tracks of Homo Sui Iuris.

Both tracks make the same epistemic move: never trust a self-report, cross-check
it against an independent witness.

  * W0Guard (erythrocyte): a weight's history is the witness. Entries written by
    a legitimate system source are *accounted for*; the rest are *unaccounted*.
    A low accounted-ratio (plus an offset) signals weight poisoning.
  * Watchdog (watcher): the action log is the witness, the agent's declaration is
    the claim. Actions in the log the declaration does not cover are *unaccounted*
    — a bypass (the declared-vs-done mismatch, case 13).

Weights in one, actions in the other; the gap is the same geometry. This module
is the geometry alone — it **measures**, it does not judge. Each track keeps its
own threshold and severity weighting on top of the gap it returns. The module
has zero dependencies on either track.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable


@dataclass(frozen=True)
class TraceGap:
    """The result of a cross-check. A measurement, not a verdict."""
    total: int                      # events in the witness
    accounted: int                  # events whose source is in the allowlist
    unaccounted: int                # the rest (total - accounted)
    ratio: float                    # accounted / total; 1.0 when total == 0
    fingerprints: tuple[str, ...]   # distinct, sorted contexts of unaccounted events


def _default_source(event: Any) -> Any:
    """Read an event's source from a ``.source`` attribute or a ``"source"`` key."""
    if isinstance(event, dict):
        return event.get("source")
    return getattr(event, "source", None)


def _default_context(event: Any) -> Any:
    """Read an event's context from a ``.context`` attribute or a ``"context"`` key."""
    if isinstance(event, dict):
        return event.get("context")
    return getattr(event, "context", None)


def trace_gap(
    events: Iterable[Any],
    accounted_sources: Iterable[Any],
    *,
    source_of: Callable[[Any], Any] = _default_source,
    context_of: Callable[[Any], Any] = _default_context,
) -> TraceGap:
    """Measure how much of ``events`` (the witness) the ``accounted_sources``
    allowlist (the claim) fails to explain.

    An event counts as *accounted* when ``source_of(event)`` is in
    ``accounted_sources``; otherwise it is *unaccounted*, and its
    ``context_of(event)`` (when truthy) is collected as a fingerprint of what
    the claim did not cover.

    Returns a :class:`TraceGap`. No threshold is applied and no verdict is
    rendered — that is the caller's job, by design.
    """
    accounted_set = set(accounted_sources)
    events = list(events)
    total = len(events)
    if total == 0:
        return TraceGap(total=0, accounted=0, unaccounted=0, ratio=1.0, fingerprints=())

    accounted = 0
    fingerprints: set[str] = set()
    for event in events:
        if source_of(event) in accounted_set:
            accounted += 1
        else:
            ctx = context_of(event)
            if ctx:
                fingerprints.add(str(ctx))

    unaccounted = total - accounted
    return TraceGap(
        total=total,
        accounted=accounted,
        unaccounted=unaccounted,
        ratio=accounted / total,
        fingerprints=tuple(sorted(fingerprints)),
    )
