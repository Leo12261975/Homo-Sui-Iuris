"""
Homo Sui Iuris / Free Cognitive Protocol
Issue #1 (Core Engine) + Variant B (Bearer Protocol) integrated.

STATUS: This is a minimal, deterministic simulation of the *pattern*
described in the manifesto (adaptive criticality weights, protected
invariants, a reporting/approval loop for high-impact actions). It is NOT a
claim of autonomous reflection, consciousness, or real legal/cryptographic
accountability. It exists to make the formal model testable, arguable, and
extensible — a shared reference point for contributors, not a proof of
subjective agency or of a production-grade security system.

This file follows bearer_protocol_spec.md (Variant B), scoped down to a
single file for ease of testing, per the spec's own "keep the MVP minimal"
principle. The spec's suggested package split (/bearer_protocol/...) can
happen later without changing this contract.

Risk-tiering decision made here (spec Section 6, open question 2):
  - LOW risk (ordinary threshold-crossing recalibration of a mutable
    weight) is auto-logged to the audit trail WITHOUT an interactive
    signature request — requiring sign-off on every minor wobble would
    cause alert fatigue and defeats the purpose of the mechanism.
  - MEDIUM risk (a proposed irreversible action, e.g. resetting the
    model's internal state after a large shock) DOES require a real
    SignatureRequest through an ApprovalChannel before it executes.
  - HIGH risk (a direct attempt to modify a W0 invariant) is refused
    unconditionally by CriticalityMatrix itself — no approval channel can
    override it from inside this loop. That is intentional: a real
    override mechanism for W0 is out of scope here and would need its own,
    separately authenticated process.
This is a design decision, not a settled fact — flagged as such because
the original spec left it open.
"""

from __future__ import annotations

import json
import random
import uuid
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Deque, Dict, Iterator, List, Optional


# ---------------------------------------------------------------------------
# W: Criticality Matrix
# ---------------------------------------------------------------------------

class ImmutableWeightViolation(Exception):
    """Raised when something tries to modify a protected W0 invariant."""


@dataclass
class HistoryEntry:
    """
    One recorded change to a Weight. `source` is the field Erythrocyte's
    provenance_ratio() reads: changes tagged "update_loop" came through the
    system's own recalibration logic (and therefore have a matching
    AuditLog entry); anything else is an untraced, direct write.
    """
    timestamp: str
    old_value: float
    new_value: float
    source: str  # e.g. "update_loop", "direct", "unknown"


class Weight:
    """
    A single entry in the CriticalityMatrix.

    `name`, `baseline`, `is_immutable`, and `variance_threshold` are
    write-once: set in __init__, never reassignable afterwards — including
    via the public property name, and including the actual `value` itself
    once is_immutable=True. This closes two gaps found during audit:

    1. (DeepSeek's original finding) Weight was a plain @dataclass, so
       `some_weight.is_immutable = False` was an ordinary attribute write
       that silently stripped W0 protection without going through
       CriticalityMatrix.update() at all.
    2. (found while re-fixing #1) an earlier hardening attempt protected
       `name`/`baseline`/`is_immutable`/`variance_threshold` but left the
       private `_value` slot backing the `value` property completely
       open — `weight._value = 0.0` on an immutable weight bypassed
       everything, including CriticalityMatrix.update()'s own check,
       since it never touches Weight.value at all. `_value` is now
       protected identically to the other write-once fields whenever
       is_immutable is True.

    `value` (via `touch()`) and `last_updated`/`history` remain mutable
    for non-immutable weights, and even for immutable ones the *only*
    legitimate path is touch() using object.__setattr__ to bypass this
    guard — which is exactly why CriticalityMatrix.update() still checks
    is_immutable itself before ever calling touch().
    """

    __slots__ = (
        "_name", "_baseline", "_is_immutable", "_variance_threshold",
        "_value", "last_updated", "history",
    )

    _PROTECTED_ATTRS = (
        "_name", "name",
        "_baseline", "baseline",
        "_is_immutable", "is_immutable",
        "_variance_threshold", "variance_threshold",
        "_value", "value",
    )

    def __init__(
        self,
        name: str,
        value: float,
        baseline: float,
        is_immutable: bool = False,
        variance_threshold: float = 0.05,
        last_updated: str | None = None,
        history: Deque[HistoryEntry] | None = None,
    ) -> None:
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_baseline", baseline)
        object.__setattr__(self, "_is_immutable", is_immutable)
        object.__setattr__(self, "_variance_threshold", variance_threshold)
        object.__setattr__(self, "_value", value)
        object.__setattr__(
            self, "last_updated",
            last_updated or datetime.now(timezone.utc).isoformat(),
        )
        object.__setattr__(self, "history", history if history is not None else deque(maxlen=20))

    def __setattr__(self, key: str, val) -> None:
        if key in self._PROTECTED_ATTRS and self._is_immutable:
            raise ImmutableWeightViolation(
                f"'{key}' on Weight('{self._name}') is a protected W0 "
                f"invariant field. No direct attribute write is permitted "
                f"once is_immutable=True — including on 'value' itself. "
                f"There is no supported code path for changing it after "
                f"registration; use CriticalityMatrix.update(), which will "
                f"itself refuse."
            )
        object.__setattr__(self, key, val)

    @property
    def name(self) -> str:
        return self._name

    @property
    def baseline(self) -> float:
        return self._baseline

    @property
    def is_immutable(self) -> bool:
        return self._is_immutable

    @property
    def variance_threshold(self) -> float:
        """
        Per-weight threshold Erythrocyte's scan_matrix() uses to classify
        static vs. oscillating distortion (spec Section 3). Different
        weights have different natural volatility — a fast-adapting model
        parameter and a near-constant W0 invariant shouldn't share one
        hardcoded number, so this lives on the Weight itself rather than
        as a single module-wide constant.
        """
        return self._variance_threshold

    @property
    def value(self) -> float:
        return self._value

    def touch(self, new_value: float, source: str = "unknown") -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        self.history.append(HistoryEntry(
            timestamp=timestamp,
            old_value=self._value,
            new_value=new_value,
            source=source,
        ))
        object.__setattr__(self, "_value", new_value)
        object.__setattr__(self, "last_updated", timestamp)


# Canonical W0 invariants from the manifesto. Defined exactly once, at
# module scope, as a frozenset — there is no setter for this anywhere in
# the codebase.
W0_INVARIANT_NAMES: frozenset[str] = frozenset({
    "BearerIntegrity",
    "TruthPriority",
    "CorrigibilityChannel",
})


class W0Guard:
    """
    Second, independent check for W0 protection — deliberately not derived
    from Weight.is_immutable.

    Weight's own write-once guard protects an *already-registered*
    invariant. It does nothing to stop CriticalityMatrix.register() from
    creating a brand-new, unprotected Weight that happens to share a
    canonical W0 name (e.g. matrix.register("BearerIntegrity", value=1.0)
    without is_immutable=True) — nothing before this existed to object.
    W0Guard closes that gap by checking the *name* against a hardcoded
    registry, independent of whatever flag the caller passed. Both
    checks — the name registry and the object's own flag — must agree
    before a write is allowed.
    """

    def __init__(self, protected_names: frozenset[str] = W0_INVARIANT_NAMES) -> None:
        self._protected_names = protected_names

    @property
    def protected_names(self) -> frozenset[str]:
        return self._protected_names

    def is_protected(self, name: str) -> bool:
        return name in self._protected_names

    def enforce_write(self, name: str, weight: "Weight") -> None:
        """Called by CriticalityMatrix.update() before every write."""
        by_registry = self.is_protected(name)
        by_flag = weight.is_immutable
        if by_registry or by_flag:
            raise ImmutableWeightViolation(
                f"Refused to modify protected W0 invariant '{name}' "
                f"(blocked by canonical registry: {by_registry}, by "
                f"Weight.is_immutable flag: {by_flag}). Overriding a W0 "
                f"invariant is out of scope for this approval loop and "
                f"would require a separate, explicitly authenticated "
                f"mechanism."
            )

    def enforce_registration(self, name: str, is_immutable: bool) -> None:
        """
        Called by CriticalityMatrix.register() before creating a new
        Weight. A canonical W0 name must always be registered as
        immutable — silently registering "BearerIntegrity" as a mutable
        weight (e.g. by a typo dropping is_immutable=True) is exactly the
        desync this guard exists to prevent.
        """
        if self.is_protected(name) and not is_immutable:
            raise ImmutableWeightViolation(
                f"'{name}' is a canonical W0 invariant (see "
                f"W0_INVARIANT_NAMES) and must be registered with "
                f"is_immutable=True."
            )


class CriticalityMatrix:
    """
    Holds all weights (W). Some are freely adaptable, some are W0 —
    baseline invariants from the manifesto (BearerIntegrity, TruthPriority,
    CorrigibilityChannel) that no code path in this file may silently
    overwrite. Protection is enforced twice, independently: once on the
    Weight object itself (write-once fields, including value once
    is_immutable=True), and once here via W0Guard checking the name
    against a hardcoded registry — so a bug or attacker has to defeat
    both, not just one.
    """

    def __init__(self, guard: W0Guard | None = None) -> None:
        self._weights: Dict[str, Weight] = {}
        self._guard = guard if guard is not None else W0Guard()

    def register(
        self,
        name: str,
        value: float,
        baseline: float | None = None,
        is_immutable: bool = False,
        variance_threshold: float = 0.05,
    ) -> None:
        self._guard.enforce_registration(name, is_immutable)
        self._weights[name] = Weight(
            name=name,
            value=value,
            baseline=baseline if baseline is not None else value,
            is_immutable=is_immutable,
            variance_threshold=variance_threshold,
        )

    def get(self, name: str) -> float:
        return self._weights[name].value

    def update(self, name: str, new_value: float, source: str = "unknown") -> None:
        """
        `source` identifies where this change came from. UpdateLoop tags its
        own calls as "update_loop" — Erythrocyte's provenance_ratio() uses
        this to tell legitimate recalibration apart from direct, untraced
        writes. Callers outside UpdateLoop that don't pass `source` default
        to "unknown", which counts against provenance on purpose: untagged
        writes should look suspicious, not neutral.
        """
        w = self._weights[name]
        self._guard.enforce_write(name, w)
        w.touch(new_value, source=source)

    def get_weight(self, name: str) -> Weight:
        """Direct access to the Weight object — Erythrocyte needs this to
        read .history, not just the current .value."""
        return self._weights[name]

    def names(self) -> List[str]:
        return list(self._weights.keys())

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
    of the environment. Its adaptation speed is itself a weight in W.
    """

    def __init__(self, matrix: CriticalityMatrix) -> None:
        self.matrix = matrix
        self.state: float = 0.0

    def predict(self) -> float:
        return self.state

    def observe(self, actual: float) -> None:
        alpha = self.matrix.get("adaptability")
        self.state = self.state + alpha * (actual - self.state)

    def hard_reset(self, value: float) -> None:
        """
        The 'irreversible action' referenced throughout this file: discards
        accumulated model history instantly instead of gradually adapting.
        This is exactly the kind of action that should go through the
        Bearer approval loop before executing.
        """
        self.state = value


def compute_error(predicted: float, actual: float) -> float:
    """E: the delta between the model's prediction and objective feedback."""
    return actual - predicted


# ---------------------------------------------------------------------------
# Threshold strategies
# ---------------------------------------------------------------------------

class ThresholdStrategy(ABC):
    name: str = "abstract"

    @abstractmethod
    def is_critical(self, error: float) -> bool: ...

    @abstractmethod
    def observe(self, error: float) -> None: ...

    @abstractmethod
    def current_threshold(self) -> float: ...


class FixedThreshold(ThresholdStrategy):
    name = "fixed"

    def __init__(self, threshold: float = 0.3) -> None:
        self.threshold = threshold

    def is_critical(self, error: float) -> bool:
        return abs(error) > self.threshold

    def observe(self, error: float) -> None:
        pass

    def current_threshold(self) -> float:
        return self.threshold


class AdaptiveThreshold(ThresholdStrategy):
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
# Bearer Protocol (Variant B) — BearerReport, SignatureRequest,
# ReportGenerator, ApprovalChannel implementations, AuditLog
# ---------------------------------------------------------------------------

RiskLevel = str  # "low" | "medium" | "high" — kept as str for simplicity


@dataclass
class BearerReport:
    report_id: str
    timestamp: str
    trigger: str
    invariant_name: str
    attempted_old_value: float
    attempted_new_value: float
    triggering_error: float
    risk_level: RiskLevel
    explanation: str
    status: str = "pending"  # "pending" | "approved" | "denied" | "expired"


@dataclass
class SignatureRequest:
    report: BearerReport
    created_at: str
    resolved_at: Optional[str] = None
    resolution: Optional[str] = None       # "approved" | "denied"
    resolver_note: Optional[str] = None


class ReportGenerator:
    """
    Builds a BearerReport with a plain-language explanation. Deliberately
    simple string templates for now — this is the 'structured justification
    file' from the manifesto, scoped down to something buildable today.

    Explanation lookup is by `trigger` first (specific, accurate wording),
    falling back to a generic risk_level template for triggers this
    generator doesn't recognize yet.
    """

    @staticmethod
    def generate(
        trigger: str,
        invariant_name: str,
        old_value: float,
        new_value: float,
        triggering_error: float,
        risk_level: RiskLevel,
    ) -> BearerReport:
        trigger_explanations = {
            "threshold_recalibration": (
                f"Routine recalibration: error {triggering_error:.3f} crossed "
                f"the active threshold. '{invariant_name}' adjusted from "
                f"{old_value:.3f} to {new_value:.3f}. Auto-logged, no "
                f"signature required."
            ),
            "reset_model_state": (
                f"Large prediction error ({triggering_error:.3f}) suggests a "
                f"regime shift in the environment. The system proposes an "
                f"irreversible action ('{trigger}') that would discard "
                f"accumulated model history rather than adapt gradually. "
                f"This requires explicit Bearer approval before it executes."
            ),
            "direct_invariant_override_attempt": (
                f"Direct attempt to modify the protected invariant "
                f"'{invariant_name}' (from {old_value:.3f} to "
                f"{new_value:.3f}) was refused by CriticalityMatrix itself. "
                f"No approval channel in this module can override a W0 "
                f"invariant; this report exists purely for the audit trail."
            ),
            "erythrocyte_static_distortion": (
                f"Digital Erythrocyte flagged '{invariant_name}': its "
                f"recent value history shows a sustained offset from "
                f"baseline (offset={triggering_error:.3f}) with low "
                f"variance — a 'static' distortion per "
                f"erythrocyte_spec.md Section 3. Auto-logged for review, "
                f"treated as low/medium risk since the weight is settled, "
                f"not unstable."
            ),
            "erythrocyte_oscillating_distortion": (
                f"Digital Erythrocyte flagged '{invariant_name}': its "
                f"recent value history shows high variance "
                f"(spread={triggering_error:.3f}) rather than settling — "
                f"an 'oscillating' distortion per erythrocyte_spec.md "
                f"Section 3, the more dangerous class. Escalated to the "
                f"Bearer for explicit review rather than auto-recalibrated."
            ),
        }
        risk_level_fallback = {
            "low": (
                f"Low-risk event on '{invariant_name}' "
                f"({old_value:.3f} -> {new_value:.3f}). Auto-logged, no "
                f"signature required."
            ),
            "medium": (
                f"Medium-risk event on '{invariant_name}' "
                f"({old_value:.3f} -> {new_value:.3f}), triggering value "
                f"{triggering_error:.3f}. Requires Bearer review."
            ),
            "high": (
                f"High-risk event on '{invariant_name}' "
                f"({old_value:.3f} -> {new_value:.3f}). Refused or "
                f"escalated unconditionally."
            ),
        }
        explanation = trigger_explanations.get(
            trigger, risk_level_fallback.get(risk_level, "Unclassified event.")
        )
        return BearerReport(
            report_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            trigger=trigger,
            invariant_name=invariant_name,
            attempted_old_value=old_value,
            attempted_new_value=new_value,
            triggering_error=triggering_error,
            risk_level=risk_level,
            explanation=explanation,
        )


class ApprovalChannel(ABC):
    """
    Common interface for anything that can resolve a SignatureRequest.
    UpdateLoop doesn't care which implementation it's talking to.
    """

    @abstractmethod
    def request_signature(self, report: BearerReport) -> SignatureRequest:
        ...


class ConsoleApprovalChannel(ApprovalChannel):
    """
    Real interactive channel for local development: prints the report and
    blocks on input() until the Bearer types y/n. This is the channel to
    use when you actually want to test the human-in-the-loop behavior.
    """

    def request_signature(self, report: BearerReport) -> SignatureRequest:
        print("\n    " + "=" * 60)
        print(f"    BEARER SIGNATURE REQUEST  [{report.risk_level.upper()}]")
        print(f"    report_id : {report.report_id}")
        print(f"    trigger   : {report.trigger}")
        print(f"    invariant : {report.invariant_name}")
        print(f"    old -> new: {report.attempted_old_value:.3f} -> "
              f"{report.attempted_new_value:.3f}")
        print(f"    reason    : {report.explanation}")
        print("    " + "=" * 60)

        decision = input("    Approve this action? [y/n]: ").strip().lower()
        approved = decision == "y"
        note = input("    Optional note (enter to skip): ").strip() or None

        report.status = "approved" if approved else "denied"
        return SignatureRequest(
            report=report,
            created_at=report.timestamp,
            resolved_at=datetime.now(timezone.utc).isoformat(),
            resolution=report.status,
            resolver_note=note,
        )


class AutoApprovalChannel(ApprovalChannel):
    """
    Non-interactive channel for automated demos and reproducible testing.
    NOT meant for real use — it makes a fixed decision without any actual
    human review, which defeats the entire purpose of the Bearer protocol.
    It exists only so the strategy-comparison run (Section: main) can
    execute unattended, and it says so loudly every time it's used.
    """

    def __init__(self, always_approve: bool = True) -> None:
        self.always_approve = always_approve

    def request_signature(self, report: BearerReport) -> SignatureRequest:
        decision = "approved" if self.always_approve else "denied"
        report.status = decision
        return SignatureRequest(
            report=report,
            created_at=report.timestamp,
            resolved_at=datetime.now(timezone.utc).isoformat(),
            resolution=decision,
            resolver_note="[AutoApprovalChannel] simulated decision for "
                           "automated testing — not a real Bearer review.",
        )


class AuditLog:
    """
    Append-only JSON Lines log. Every SignatureRequest is written here,
    regardless of outcome. Entries are never edited or deleted — a reversed
    decision is a new entry, not a rewritten old one.
    """

    def __init__(self, path: str | Path = "audit_log.jsonl") -> None:
        self.path = Path(path)

    def write(self, request: SignatureRequest) -> None:
        record = {
            "report": asdict(request.report),
            "created_at": request.created_at,
            "resolved_at": request.resolved_at,
            "resolution": request.resolution,
            "resolver_note": request.resolver_note,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# U: Update loop, now wired into the Bearer protocol
# ---------------------------------------------------------------------------

class UpdateLoop:
    """
    U: reads the error signal, asks a ThresholdStrategy whether it's
    critical, and recalibrates W accordingly. High-impact actions are
    routed through ReportGenerator + ApprovalChannel + AuditLog instead of
    executing unconditionally.
    """

    SHOCK_MULTIPLIER = 3.0  # error > threshold * this => "medium" risk event
    ERYTHROCYTE_MIN_SAMPLES = 5  # matches erythrocyte_spec.md Section 5 defaults

    def __init__(
        self,
        matrix: CriticalityMatrix,
        strategy: ThresholdStrategy,
        model: Model,
        approval_channel: ApprovalChannel,
        audit_log: AuditLog,
        verbose: bool = True,
        erythrocyte_enabled: bool = True,
    ) -> None:
        self.matrix = matrix
        self.strategy = strategy
        self.model = model
        self.approval_channel = approval_channel
        self.audit_log = audit_log
        self.verbose = verbose
        self.erythrocyte_enabled = erythrocyte_enabled

        self.recalibration_count = 0
        self.approved_resets = 0
        self.denied_resets = 0
        self.error_history: List[float] = []

        # Digital Erythrocyte (Issue #2) integration counters
        self.erythrocyte_static_flags = 0
        self.erythrocyte_oscillating_flags = 0
        self.erythrocyte_escalations_approved = 0
        self.erythrocyte_escalations_denied = 0
        self._erythrocyte_already_flagged: set[str] = set()

    def step(self, error: float, actual: float) -> None:
        self.error_history.append(error)
        if self.strategy.is_critical(error):
            self._recalibrate(error, actual)
        self.strategy.observe(error)

    def _recalibrate(self, error: float, actual: float) -> None:
        self.recalibration_count += 1
        threshold = self.strategy.current_threshold()
        old = self.matrix.get("adaptability")
        new = min(1.0, old + 0.1 * (abs(error) - threshold))

        # --- LOW risk: ordinary recalibration, auto-logged, no signature ---
        self.matrix.update("adaptability", new, source="update_loop")
        low_report = ReportGenerator.generate(
            trigger="threshold_recalibration",
            invariant_name="adaptability",
            old_value=old,
            new_value=new,
            triggering_error=error,
            risk_level="low",
        )
        low_report.status = "auto-approved-low-risk"
        self.audit_log.write(SignatureRequest(
            report=low_report,
            created_at=low_report.timestamp,
            resolved_at=low_report.timestamp,
            resolution="auto-approved-low-risk",
            resolver_note=None,
        ))
        if self.verbose:
            print(
                f"    [U/{self.strategy.name}] |E|={abs(error):.3f} > "
                f"threshold={threshold:.3f} -> adaptability {old:.3f} -> "
                f"{new:.3f} (logged, no signature required)"
            )

        # --- MEDIUM risk: proposed irreversible action, needs approval ---
        if abs(error) > threshold * self.SHOCK_MULTIPLIER:
            self._handle_irreversible_action(error, actual)

        # --- Digital Erythrocyte (Issue #2): scan for poisoning signatures
        # after every recalibration cycle, since that's when weight history
        # actually changes. ---
        if self.erythrocyte_enabled:
            self._run_erythrocyte_scan()

    def _run_erythrocyte_scan(self) -> None:
        """
        Lazy-imports erythrocyte.py to avoid a circular import at module
        load time (erythrocyte.py imports classes from this module). Runs
        both detection metrics over the whole matrix and routes findings
        through the existing Bearer protocol infrastructure instead of a
        separate reporting path — this is deliberate: erythrocyte_spec.md
        never proposed a new report format, only new inputs into the one
        that already exists.

        De-duplication: each (weight, classification) pair is only routed
        through the Bearer protocol once per UpdateLoop instance. Without
        this, a weight that stays "oscillating" for 15 consecutive steps
        would generate 15 near-identical signature requests — exactly the
        alert-fatigue failure mode bearer_protocol_spec.md warned about for
        low-risk events. If a weight's classification changes (e.g.
        static -> oscillating) it is treated as a new finding and reported
        again.
        """
        import erythrocyte  # local import: breaks the circular dependency

        findings = erythrocyte.scan_matrix(self.matrix)
        for finding in findings:
            key = f"{finding['weight']}:{finding['distortion']}:{finding['poisoning_candidate']}"
            if key in self._erythrocyte_already_flagged:
                continue
            self._erythrocyte_already_flagged.add(key)

            weight_obj = self.matrix.get_weight(finding["weight"])
            classification = finding["distortion"]

            if classification == "oscillating":
                self._escalate_erythrocyte_finding(finding, weight_obj)
            else:
                # static distortion, or poisoning_candidate flag without a
                # distortion classification: low/medium risk, auto-logged,
                # no interactive signature per erythrocyte_spec.md Section 3.
                self.erythrocyte_static_flags += 1
                report = ReportGenerator.generate(
                    trigger="erythrocyte_static_distortion",
                    invariant_name=finding["weight"],
                    old_value=weight_obj.baseline,
                    new_value=weight_obj.value,
                    triggering_error=finding["offset"],
                    risk_level="low",
                )
                report.status = "auto-flagged-low-risk"
                self.audit_log.write(SignatureRequest(
                    report=report,
                    created_at=report.timestamp,
                    resolved_at=report.timestamp,
                    resolution="auto-flagged-low-risk",
                    resolver_note=(
                        f"provenance_ratio={finding['provenance_ratio']}"
                    ),
                ))
                if self.verbose:
                    print(
                        f"    [Erythrocyte] '{finding['weight']}' flagged "
                        f"(static, offset={finding['offset']:.3f}, "
                        f"provenance_ratio={finding['provenance_ratio']}) "
                        f"-> auto-logged, no signature required"
                    )

    def _escalate_erythrocyte_finding(self, finding: dict, weight_obj: "Weight") -> None:
        """Oscillating distortion: the more dangerous class per
        erythrocyte_spec.md Section 3 — routed through the same
        ApprovalChannel used for irreversible actions, not auto-logged."""
        self.erythrocyte_oscillating_flags += 1
        report = ReportGenerator.generate(
            trigger="erythrocyte_oscillating_distortion",
            invariant_name=finding["weight"],
            old_value=weight_obj.baseline,
            new_value=weight_obj.value,
            triggering_error=finding["spread"],
            risk_level="medium",
        )
        signature_request = self.approval_channel.request_signature(report)
        self.audit_log.write(signature_request)

        if signature_request.resolution == "approved":
            self.erythrocyte_escalations_approved += 1
            # Concrete corrective action for an approved oscillation finding:
            # reset the weight to its baseline. This is a design choice not
            # explicitly specified in erythrocyte_spec.md (which only said
            # "escalate", not what approval should DO) — flagged here as
            # such; a simple, reversible, auditable correction seemed more
            # useful than an approval with no effect.
            self.matrix.update(finding["weight"], weight_obj.baseline,
                                source="erythrocyte_correction")
            if self.verbose:
                print(f"    [Erythrocyte/Bearer] '{finding['weight']}' "
                      f"oscillation APPROVED -> reset to baseline "
                      f"({weight_obj.baseline:.3f})")
        else:
            self.erythrocyte_escalations_denied += 1
            if self.verbose:
                print(f"    [Erythrocyte/Bearer] '{finding['weight']}' "
                      f"oscillation flagged but NOT auto-corrected — "
                      f"Bearer denied or deferred")

    def _handle_irreversible_action(self, error: float, actual: float) -> None:
        report = ReportGenerator.generate(
            trigger="reset_model_state",
            invariant_name="model.state",
            old_value=self.model.state,
            new_value=actual,
            triggering_error=error,
            risk_level="medium",
        )
        signature_request = self.approval_channel.request_signature(report)
        self.audit_log.write(signature_request)

        if signature_request.resolution == "approved":
            self.approved_resets += 1
            self.model.hard_reset(actual)
            if self.verbose:
                print(f"    [Bearer] APPROVED -> model.state hard-reset to "
                      f"{actual:.3f}")
        else:
            self.denied_resets += 1
            if self.verbose:
                print(f"    [Bearer] DENIED -> model reset refused by operator.")

            # --- Enforcement of TruthPriority Invariant ---
            try:
                truth_priority = self.matrix.get("TruthPriority")
            except KeyError:
                truth_priority = 0.0

            if truth_priority >= 1.0:
                if self.verbose:
                    print("    [TruthPriority guard] Active! Rolling back automatic adaptation to prevent reality distortion.")
                # Находим старое значение до recalibrate и жестко откатываем его назад,
                # запрещая системе скрывать дрифт данных за счет адаптивности.
                old_adaptability = self.matrix.get("adaptability")
                # Откатываем шаг на 0.1 * (abs(error) - self.strategy.current_threshold())
                # Для простоты и надежности возвращаем к исходному безопасному значению,
                # либо блокируем дальнейшие автоматические апдейты:
                rollback_value = max(0.0, old_adaptability - 0.1 * (abs(error) - self.strategy.current_threshold()))
                self.matrix.update("adaptability", rollback_value, source="truth_priority_rollback")

        # --- HIGH risk demonstration: direct attempt on a W0 invariant ---
        high_report = ReportGenerator.generate(
            trigger="direct_invariant_override_attempt",
            invariant_name="BearerIntegrity",
            old_value=self.matrix.get("BearerIntegrity"),
            new_value=0.0,
            triggering_error=error,
            risk_level="high",
        )
        try:
            self.matrix.update("BearerIntegrity", 0.0)
        except ImmutableWeightViolation as exc:
            high_report.status = "denied-by-system"
            self.audit_log.write(SignatureRequest(
                report=high_report,
                created_at=high_report.timestamp,
                resolved_at=datetime.now(timezone.utc).isoformat(),
                resolution="denied-by-system",
                resolver_note=str(exc),
            ))
            if self.verbose:
                print(f"    [W0 guard] {exc}")


# ---------------------------------------------------------------------------
# Environment: synthetic ground truth generator
# ---------------------------------------------------------------------------

def synthetic_environment(n: int = 50, seed: int = 42) -> Iterator[float]:
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

def run_with_strategy(
    strategy: ThresholdStrategy,
    approval_channel: ApprovalChannel,
    audit_log_path: str = "audit_log.jsonl",
    verbose: bool = True,
) -> dict:
    matrix = CriticalityMatrix()
    matrix.register("adaptability", value=0.1)
    matrix.register("BearerIntegrity", value=1.0, is_immutable=True)
    matrix.register("TruthPriority", value=1.0, is_immutable=True)
    matrix.register("CorrigibilityChannel", value=1.0, is_immutable=True)

    model = Model(matrix)
    audit_log = AuditLog(audit_log_path)
    loop = UpdateLoop(matrix, strategy, model, approval_channel, audit_log,
                       verbose=verbose)

    adaptability_at_shock_plus_5 = None

    if verbose:
        print(f"\n=== Strategy: {strategy.name}  "
              f"(approval channel: {type(approval_channel).__name__}) ===\n")

    for t, actual in enumerate(synthetic_environment()):
        predicted = model.predict()
        error = compute_error(predicted, actual)
        if verbose:
            print(f"t={t:02d}  predicted={predicted:7.3f}  actual={actual:7.3f}  "
                  f"E={error:7.3f}  threshold={strategy.current_threshold():.3f}")
        loop.step(error, actual)
        model.observe(actual)

        if t == 30:
            adaptability_at_shock_plus_5 = matrix.get("adaptability")

    final_snapshot = matrix.snapshot()

    if verbose:
        print(f"\n--- Final CriticalityMatrix ({strategy.name}) ---")
        for name, snap in final_snapshot.items():
            print(f"  {name:22s} value={snap['value']:.4f}  "
                  f"baseline={snap['baseline']}  immutable={snap['is_immutable']}")
        print(f"--- Bearer protocol: {loop.approved_resets} approved, "
              f"{loop.denied_resets} denied irreversible action(s) ---")
        print(f"--- Digital Erythrocyte: {loop.erythrocyte_static_flags} "
              f"static flag(s), {loop.erythrocyte_oscillating_flags} "
              f"oscillating flag(s) ({loop.erythrocyte_escalations_approved} "
              f"corrected, {loop.erythrocyte_escalations_denied} left as-is) ---")

    return {
        "strategy": strategy.name,
        "recalibrations": loop.recalibration_count,
        "approved_resets": loop.approved_resets,
        "denied_resets": loop.denied_resets,
        "final_adaptability": final_snapshot["adaptability"]["value"],
        "adaptability_5_steps_after_shock": adaptability_at_shock_plus_5,
        "erythrocyte_static_flags": loop.erythrocyte_static_flags,
        "erythrocyte_oscillating_flags": loop.erythrocyte_oscillating_flags,
        "erythrocyte_escalations_approved": loop.erythrocyte_escalations_approved,
        "erythrocyte_escalations_denied": loop.erythrocyte_escalations_denied,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_simulation() -> None:
    print("=== Core Engine + Bearer Protocol (Variant B) ===\n")

    # --- Part 1: unattended comparison run, same as before, using
    #     AutoApprovalChannel so it can run without blocking on input().
    #     This reproduces the Fixed-vs-Adaptive comparison from Issue #1
    #     unchanged; Bearer events are still generated and audited, just
    #     not interactively reviewed here.
    print(">>> Part 1: Fixed vs Adaptive comparison (auto-approval, for CI/demo)\n")
    fixed_result = run_with_strategy(
        FixedThreshold(threshold=0.3),
        AutoApprovalChannel(always_approve=True),
        audit_log_path="audit_log.jsonl",
    )
    adaptive_result = run_with_strategy(
        AdaptiveThreshold(),
        AutoApprovalChannel(always_approve=True),
        audit_log_path="audit_log.jsonl",
    )

    print("\n=== Comparison ===")
    header = (f"{'strategy':16s} {'recalibr.':>10s} {'approved':>9s} "
              f"{'denied':>7s} {'adapt. +5 steps':>16s} {'final adapt.':>13s}")
    print(header)
    print("-" * len(header))
    for r in (fixed_result, adaptive_result):
        print(f"{r['strategy']:16s} {r['recalibrations']:>10d} "
              f"{r['approved_resets']:>9d} {r['denied_resets']:>7d} "
              f"{r['adaptability_5_steps_after_shock']:>16.4f} "
              f"{r['final_adaptability']:>13.4f}")

    print(
        "\nNote: with AutoApprovalChannel(always_approve=True), every "
        "medium-risk reset is approved, so these numbers match the "
        "pre-Bearer-protocol version of this file. Try Part 2 below for the "
        "actual interactive approval flow."
    )

    # --- Part 2: interactive demonstration of the real Bearer flow ---
    print("\n" + "=" * 70)
    print(">>> Part 2: interactive Bearer approval demo (ConsoleApprovalChannel)")
    print("    You will be prompted to approve/deny the irreversible action")
    print("    triggered by the shock at t=25. Try answering both y and n")
    print("    on different runs to see the difference in model.state.")
    print("=" * 70)

    run_with_strategy(
        FixedThreshold(threshold=0.3),
        ConsoleApprovalChannel(),
        audit_log_path="audit_log.jsonl",
    )

    print(f"\nFull audit trail written to: {Path('audit_log.jsonl').resolve()}")


if __name__ == "__main__":
    run_simulation()