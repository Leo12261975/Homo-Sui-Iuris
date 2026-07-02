"""
Homo Sui Iuris / Free Cognitive Protocol
Issue #1 — Core Engine: prototype of the S = (M, E, W, U) cognitive loop.

STATUS: This is a minimal, deterministic simulation of the *pattern* described
in the manifesto (adaptive criticality weights, protected invariants). It is
NOT a claim of autonomous reflection, consciousness, or "free will" in any
strong sense. It exists to make the formal model testable, arguable, and
extensible — a shared reference point for contributors, not a proof of
subjective agency.

Data contract (this is the part that issue #2 and #3 will build on):
    Weight             -> a single named value inside the CriticalityMatrix
    CriticalityMatrix  -> named collection of Weight objects, with a hard
                           distinction between mutable weights and immutable
                           W0 invariants
    Model (M)          -> holds internal state, produces predictions
    ErrorSignal (E)    -> delta between prediction and ground truth
    ThresholdStrategy  -> decides whether a given error counts as "critical"
                           (two implementations below: fixed vs. adaptive/EMA)
    UpdateLoop (U)     -> reads E, asks the ThresholdStrategy, and if needed
                           recalibrates W — always respecting W0

This version runs TWO threshold strategies side by side on the same
synthetic environment, so the trade-off between "simple and predictable"
and "closer to the manifesto's idea of evolving criticality" is visible
directly in the output, not just asserted in prose.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterator, List


# ---------------------------------------------------------------------------
# W: Criticality Matrix
# ---------------------------------------------------------------------------

class ImmutableWeightViolation(Exception):
    """Raised when the update loop tries to modify a protected W0 invariant."""


@dataclass
class Weight:
    name: str
    value: float
    baseline: float
    is_immutable: bool = False
    last_updated: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def touch(self, new_value: float) -> None:
        self.value = new_value
        self.last_updated = datetime.now(timezone.utc).isoformat()


class CriticalityMatrix:
    """
    Holds all weights (W). Some are freely adaptable, some are W0 —
    baseline invariants from the manifesto (BearerIntegrity, Truth-Priority,
    CorrigibilityChannel) that the update loop may never silently overwrite.
    """

    def __init__(self) -> None:
        self._weights: Dict[str, Weight] = {}

    def register(
        self,
        name: str,
        value: float,
        baseline: float | None = None,
        is_immutable: bool = False,
    ) -> None:
        self._weights[name] = Weight(
            name=name,
            value=value,
            baseline=baseline if baseline is not None else value,
            is_immutable=is_immutable,
        )

    def get(self, name: str) -> float:
        return self._weights[name].value

    def update(self, name: str, new_value: float) -> None:
        w = self._weights[name]
        if w.is_immutable:
            raise ImmutableWeightViolation(
                f"Refused to modify protected W0 invariant '{name}'. "
                f"BearerIntegrity requires explicit human override, not an "
                f"autonomous update."
            )
        w.touch(new_value)

    def snapshot(self) -> Dict[str, dict]:
        return {
            name: {
                "value": round(w.value, 4),
                "baseline": w.baseline,
                "is_immutable": w.is_immutable,
                "last_updated": w.last_updated,
            }
            for name, w in self._weights.items()
        }


# ---------------------------------------------------------------------------
# M: Model  /  E: Error signal
# ---------------------------------------------------------------------------

class Model:
    """
    Minimal predictive model: an exponentially-weighted moving estimate
    of the environment. Its adaptation speed is itself a weight in W,
    which is exactly what makes it subject to the U loop.
    """

    def __init__(self, matrix: CriticalityMatrix) -> None:
        self.matrix = matrix
        self.state: float = 0.0

    def predict(self) -> float:
        return self.state

    def observe(self, actual: float) -> None:
        alpha = self.matrix.get("adaptability")
        self.state = self.state + alpha * (actual - self.state)


def compute_error(predicted: float, actual: float) -> float:
    """E: the delta between the model's prediction and objective feedback."""
    return actual - predicted


# ---------------------------------------------------------------------------
# Threshold strategies — the "Fixed vs Adaptive" comparison
# ---------------------------------------------------------------------------

class ThresholdStrategy(ABC):
    """
    Common interface: given the current error (and whatever internal state
    the strategy wants to keep), decide whether it counts as critical.
    UpdateLoop doesn't care which implementation it's talking to.
    """

    name: str = "abstract"

    @abstractmethod
    def is_critical(self, error: float) -> bool:
        ...

    @abstractmethod
    def observe(self, error: float) -> None:
        """Let the strategy update its own internal state after each step."""
        ...

    @abstractmethod
    def current_threshold(self) -> float:
        ...


class FixedThreshold(ThresholdStrategy):
    """Simple, predictable, does not change. Easy to reason about and test."""

    name = "fixed"

    def __init__(self, threshold: float = 0.3) -> None:
        self.threshold = threshold

    def is_critical(self, error: float) -> bool:
        return abs(error) > self.threshold

    def observe(self, error: float) -> None:
        pass  # fixed strategy learns nothing from history, by design

    def current_threshold(self) -> float:
        return self.threshold


class AdaptiveThreshold(ThresholdStrategy):
    """
    Threshold itself evolves via an exponential moving average (EMA) of
    recent absolute error, scaled by a sensitivity factor. Closer to the
    manifesto's language of a system that recalibrates based on its own
    history rather than a fixed external rule — at the cost of being
    harder to predict and to reason about in advance.
    """

    name = "adaptive (EMA)"

    def __init__(self, sensitivity: float = 1.5, ema_alpha: float = 0.2,
                 floor: float = 0.15) -> None:
        self.sensitivity = sensitivity
        self.ema_alpha = ema_alpha
        self.floor = floor
        self._ema_abs_error: float = floor

    def is_critical(self, error: float) -> bool:
        return abs(error) > self.current_threshold()

    def observe(self, error: float) -> None:
        self._ema_abs_error = (
            self.ema_alpha * abs(error)
            + (1 - self.ema_alpha) * self._ema_abs_error
        )

    def current_threshold(self) -> float:
        return max(self.floor, self.sensitivity * self._ema_abs_error)


# ---------------------------------------------------------------------------
# U: Update loop
# ---------------------------------------------------------------------------

def request_bearer_approval(action: str, log: bool = True) -> bool:
    """
    Stub for the DCT / Bearer mechanism (issue #2/#3 territory).
    In this MVP it just simulates a human-in-the-loop checkpoint —
    it does not actually block execution, it only marks the moment
    where a real implementation would.
    """
    if log:
        print(f"    [DCT-stub] Irreversible action requested: '{action}'. "
              f"Bearer approval would be required here.")
    return True


class UpdateLoop:
    """
    U: reads the error signal, asks a ThresholdStrategy whether it's
    critical, and if so recalibrates W — always respecting W0.
    """

    def __init__(self, matrix: CriticalityMatrix, strategy: ThresholdStrategy,
                 verbose: bool = True) -> None:
        self.matrix = matrix
        self.strategy = strategy
        self.verbose = verbose
        self.recalibration_count = 0
        self.error_history: List[float] = []

    def step(self, error: float) -> None:
        self.error_history.append(error)
        critical = self.strategy.is_critical(error)
        if critical:
            self._recalibrate(error)
        self.strategy.observe(error)

    def _recalibrate(self, error: float) -> None:
        self.recalibration_count += 1
        threshold = self.strategy.current_threshold()
        old = self.matrix.get("adaptability")
        new = min(1.0, old + 0.1 * (abs(error) - threshold))
        self.matrix.update("adaptability", new)
        if self.verbose:
            print(
                f"    [U/{self.strategy.name}] |E|={abs(error):.3f} > "
                f"threshold={threshold:.3f} -> adaptability {old:.3f} -> {new:.3f}"
            )

        if abs(error) > threshold * 3:
            request_bearer_approval("reset_model_state", log=self.verbose)
            try:
                self.matrix.update("BearerIntegrity", 0.0)
            except ImmutableWeightViolation as exc:
                if self.verbose:
                    print(f"    [W0 guard] {exc}")


# ---------------------------------------------------------------------------
# Environment: synthetic ground truth generator
# ---------------------------------------------------------------------------

def synthetic_environment(n: int = 50, seed: int = 42) -> Iterator[float]:
    """
    Slow drift + gaussian noise + one deliberate regime shock at t=25,
    so both threshold strategies have something real to react to.
    Deterministic (fixed seed) so the two strategies are compared on
    exactly the same environment.
    """
    rng = random.Random(seed)
    value = 0.0
    for t in range(n):
        drift = 0.02
        noise = rng.gauss(0, 0.05)
        shock = 1.5 if t == 25 else 0.0
        value += drift + noise + shock
        yield value


# ---------------------------------------------------------------------------
# Running one strategy end-to-end
# ---------------------------------------------------------------------------

def run_with_strategy(strategy: ThresholdStrategy, verbose: bool = True) -> dict:
    matrix = CriticalityMatrix()
    matrix.register("adaptability", value=0.1)
    matrix.register("BearerIntegrity", value=1.0, is_immutable=True)
    matrix.register("TruthPriority", value=1.0, is_immutable=True)
    matrix.register("CorrigibilityChannel", value=1.0, is_immutable=True)

    model = Model(matrix)
    loop = UpdateLoop(matrix, strategy, verbose=verbose)

    adaptability_at_shock_plus_5 = None

    if verbose:
        print(f"\n=== Strategy: {strategy.name} ===\n")

    for t, actual in enumerate(synthetic_environment()):
        predicted = model.predict()
        error = compute_error(predicted, actual)
        if verbose:
            print(f"t={t:02d}  predicted={predicted:7.3f}  actual={actual:7.3f}  "
                  f"E={error:7.3f}  threshold={strategy.current_threshold():.3f}")
        loop.step(error)
        model.observe(actual)

        if t == 30:  # 5 steps after the shock at t=25
            adaptability_at_shock_plus_5 = matrix.get("adaptability")

    final_snapshot = matrix.snapshot()

    if verbose:
        print(f"\n--- Final CriticalityMatrix ({strategy.name}) ---")
        for name, snap in final_snapshot.items():
            print(f"  {name:22s} value={snap['value']:.4f}  "
                  f"baseline={snap['baseline']}  immutable={snap['is_immutable']}")

    return {
        "strategy": strategy.name,
        "recalibrations": loop.recalibration_count,
        "final_adaptability": final_snapshot["adaptability"]["value"],
        "adaptability_5_steps_after_shock": adaptability_at_shock_plus_5,
    }


# ---------------------------------------------------------------------------
# Main: run both strategies, compare
# ---------------------------------------------------------------------------

def run_simulation() -> None:
    print("=== Core Engine: S = (M, E, W, U) simulation ===")
    print("Comparing FixedThreshold vs AdaptiveThreshold (EMA) on the same environment.\n")

    fixed_result = run_with_strategy(FixedThreshold(threshold=0.3))
    adaptive_result = run_with_strategy(AdaptiveThreshold())

    print("\n=== Comparison ===")
    header = f"{'strategy':16s} {'recalibrations':>15s} {'adapt. +5 steps':>18s} {'final adapt.':>14s}"
    print(header)
    print("-" * len(header))
    for r in (fixed_result, adaptive_result):
        print(f"{r['strategy']:16s} {r['recalibrations']:>15d} "
              f"{r['adaptability_5_steps_after_shock']:>18.4f} "
              f"{r['final_adaptability']:>14.4f}")

    print(
        "\nReading this: FixedThreshold reacts to any error above a constant "
        "line, regardless of context — predictable, but blind to whether the "
        "environment has generally become noisier. AdaptiveThreshold raises "
        "its own bar after a shock (because recent error is now higher on "
        "average), which can mean fewer recalibrations right after a big "
        "surprise, but is harder to predict in advance and depends on tuning "
        "(sensitivity, EMA alpha) that isn't obviously 'correct'. Neither is "
        "strictly better — that trade-off is the point of showing both."
    )


if __name__ == "__main__":
    run_simulation()
