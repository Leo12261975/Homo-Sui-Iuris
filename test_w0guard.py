"""
Tests for Weight / W0Guard / CriticalityMatrix (core_engine.py).

Scope note: this file covers ONLY the immutability mechanism itself —
Weight's write-once fields and W0Guard's two independent checks. The
"threshold in the wrong file" regression (Variant 1: leukocyte_protocol.py
using FixedThreshold(0.3) instead of a value low enough to trigger
_recalibrate()) is a separate concern that never goes through W0Guard at
all, and belongs in its own test file (test_leukocyte_integration.py),
not here — mixing the two would blur what "test_w0guard.py failing" is
supposed to mean.
"""

import pytest

from core_engine import (
    CriticalityMatrix,
    ImmutableWeightViolation,
    W0Guard,
    W0_INVARIANT_NAMES,
    Weight,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def matrix() -> CriticalityMatrix:
    m = CriticalityMatrix()
    m.register("adaptability", value=0.1)
    m.register("BearerIntegrity", value=1.0, is_immutable=True)
    m.register("TruthPriority", value=1.0, is_immutable=True)
    m.register("CorrigibilityChannel", value=1.0, is_immutable=True)
    return m


# ---------------------------------------------------------------------------
# enforce_write — through every entry point, not just CriticalityMatrix.update()
# ---------------------------------------------------------------------------

class TestEnforceWrite:

    def test_update_blocks_w0_invariant(self, matrix):
        """The documented, expected path: CriticalityMatrix.update()."""
        with pytest.raises(ImmutableWeightViolation):
            matrix.update("BearerIntegrity", 0.0)
        # value must be provably unchanged, not just "an exception happened"
        assert matrix.get("BearerIntegrity") == 1.0

    def test_update_allows_mutable_weight(self, matrix):
        """Negative-path sanity check: the guard must not be so broad it
        blocks ordinary, legitimate writes to non-W0 weights."""
        matrix.update("adaptability", 0.5, source="update_loop")
        assert matrix.get("adaptability") == 0.5

    def test_direct_touch_on_fetched_weight_object_blocked(self, matrix):
        """
        Bypass attempt #1: get the Weight object directly via
        matrix.get_weight() and call .touch() on it, skipping
        CriticalityMatrix.update() (and therefore W0Guard.enforce_write)
        entirely.

        touch() must now refuse this: it checks is_immutable itself
        before writing _value/last_updated/history, independent of
        whether the caller went through CriticalityMatrix.update() or
        not. This closes the gap the previous version of this test
        documented (a fetched Weight reference used to be able to bypass
        protection by calling touch() directly).
        """
        w = matrix.get_weight("BearerIntegrity")
        with pytest.raises(ImmutableWeightViolation):
            w.touch(0.0, source="direct_bypass_attempt")
        assert w.value == 1.0, (
            "touch() must refuse to change the value of an immutable "
            "weight even when called directly on a fetched reference, "
            "bypassing CriticalityMatrix.update()."
        )

    def test_direct_attribute_write_on_fetched_weight_object_blocked(self, matrix):
        """
        Bypass attempt #2: get the Weight object via matrix.get_weight()
        and try a plain attribute assignment (not through touch(), not
        through matrix.update()) — this IS gated, by Weight.__setattr__
        itself, independent of W0Guard.
        """
        w = matrix.get_weight("BearerIntegrity")
        with pytest.raises(ImmutableWeightViolation):
            w.value = 0.0
        with pytest.raises(ImmutableWeightViolation):
            w.is_immutable = False
        with pytest.raises(ImmutableWeightViolation):
            w.baseline = 0.0
        with pytest.raises(ImmutableWeightViolation):
            w.name = "not BearerIntegrity anymore"
        assert w.value == 1.0
        assert w.is_immutable is True

    def test_object_setattr_bypass_is_technically_possible(self, matrix):
        """
        Bypass attempt #3: object.__setattr__() called directly on the
        Weight instance, bypassing Weight.__setattr__ entirely (this is
        a general Python fact, not specific to this class — ANY custom
        __setattr__ can be routed around this way by code that holds a
        direct reference to the object).

        This test intentionally asserts that the bypass SUCCEEDS. The
        point is not to pretend this is impossible — it is possible, in
        pure Python, for any object with __setattr__-based protection.
        What this test documents is the actual threat model: Weight's
        write-once guard protects against careless/accidental writes and
        against code going through the normal attribute-assignment
        syntax, not against a determined caller explicitly reaching for
        object.__setattr__. If this test ever starts failing (i.e. the
        bypass gets blocked), that would mean Weight moved to something
        like __slots__ + a C-level guard or immutable-by-construction
        design — worth knowing, not worth silently ignoring either way.
        """
        w = matrix.get_weight("BearerIntegrity")
        object.__setattr__(w, "_value", 0.0)
        assert w.value == 0.0, (
            "This assertion is expected to pass today: object.__setattr__ "
            "bypasses Weight.__setattr__ by design (a Python-level fact, "
            "not a bug in this class). Documenting it, not celebrating it."
        )


# ---------------------------------------------------------------------------
# enforce_registration
# ---------------------------------------------------------------------------

class TestEnforceRegistration:

    @pytest.mark.parametrize("name", sorted(W0_INVARIANT_NAMES))
    def test_cannot_register_canonical_w0_name_as_mutable(self, name):
        m = CriticalityMatrix()
        with pytest.raises(ImmutableWeightViolation):
            m.register(name, value=1.0, is_immutable=False)
        with pytest.raises(ImmutableWeightViolation):
            m.register(name, value=1.0)  # is_immutable defaults to False

    @pytest.mark.parametrize("name", sorted(W0_INVARIANT_NAMES))
    def test_can_register_canonical_w0_name_as_immutable(self, name):
        m = CriticalityMatrix()
        m.register(name, value=1.0, is_immutable=True)
        assert m.get(name) == 1.0

    def test_ordinary_weight_registration_unaffected(self):
        """The guard must not reject registrations that have nothing to
        do with W0 names at all — sanity check against over-broad
        matching (e.g. accidental substring checks)."""
        m = CriticalityMatrix()
        m.register("adaptability", value=0.1, is_immutable=False)
        m.register("BearerIntegritySomethingElse", value=1.0, is_immutable=False)
        assert m.get("adaptability") == 0.1
        assert m.get("BearerIntegritySomethingElse") == 1.0


# ---------------------------------------------------------------------------
# W0_INVARIANT_NAMES / W0Guard's own reference to it
# ---------------------------------------------------------------------------

class TestW0GuardRegistryReference:

    def test_w0_invariant_names_is_frozenset(self):
        """
        A frozenset has no mutating methods at all (no .add/.remove/etc)
        — so the question "can someone mutate W0_INVARIANT_NAMES in
        place" has a simple answer: no, not through any public API,
        because frozenset offers none. This isn't a property W0Guard
        defends; it's a property of the type itself.
        """
        assert isinstance(W0_INVARIANT_NAMES, frozenset)
        with pytest.raises(AttributeError):
            W0_INVARIANT_NAMES.add("SomeNewInvariant")  # frozenset has no .add

    def test_reassigning_module_level_name_does_not_affect_existing_guard(self):
        """
        The only documented way to "change" W0_INVARIANT_NAMES is
        reassigning the module attribute core_engine.W0_INVARIANT_NAMES to
        a *different* frozenset object. This test confirms an existing
        W0Guard is unaffected — unsurprising, since it already holds its
        own reference from construction time.

        The more interesting, non-obvious result (verified by running
        this, not assumed) is the second half: a BRAND NEW W0Guard()
        constructed with no arguments AFTER the module attribute was
        reassigned still uses the ORIGINAL set, not the reassigned one.
        This is because `def __init__(self, protected_names=W0_INVARIANT_NAMES)`
        binds its default value once, at class-definition time (import
        time), into the function's __defaults__ — it is not a fresh
        lookup of the module global on every call. Reassigning
        core_engine.W0_INVARIANT_NAMES after import has NO effect on the
        default at all, ever, for the lifetime of the process.

        This is extra, free hardening (a runtime monkeypatch of the
        module attribute can't retroactively weaken new guards either),
        but it's non-obvious enough that it's worth asserting explicitly
        rather than leaving it as an accident nobody documented.
        """
        import core_engine

        guard = W0Guard()  # binds core_engine.W0_INVARIANT_NAMES as it is now
        original_names = guard.protected_names
        assert guard.is_protected("BearerIntegrity") is True

        # Reassign the module-level name to a frozenset that does NOT
        # include BearerIntegrity.
        core_engine.W0_INVARIANT_NAMES = frozenset({"SomethingElseEntirely"})
        try:
            # The already-constructed guard must be unaffected.
            assert guard.is_protected("BearerIntegrity") is True
            assert guard.protected_names == original_names

            # A guard constructed AFTER the reassignment, using the
            # default argument, is ALSO unaffected — not because W0Guard
            # re-reads anything, but because Python bound the default
            # value once, at import time, into __init__'s __defaults__.
            new_guard_via_default = W0Guard()
            assert new_guard_via_default.is_protected("BearerIntegrity") is True
            assert new_guard_via_default.protected_names == original_names

            # Contrast: a guard that explicitly reads the module
            # attribute fresh (bypassing the stale default) DOES see the
            # change — proving the difference is specifically about
            # default-argument binding, not some other protection.
            new_guard_explicit = W0Guard(protected_names=core_engine.W0_INVARIANT_NAMES)
            assert new_guard_explicit.is_protected("BearerIntegrity") is False
        finally:
            core_engine.W0_INVARIANT_NAMES = frozenset(original_names)

    def test_custom_protected_names_are_isolated_between_instances(self):
        """A W0Guard built with an explicit custom set must not share
        state with one built from the module default — regression guard
        against a future refactor accidentally making protected_names a
        mutable class-level attribute shared across instances."""
        custom_guard = W0Guard(protected_names=frozenset({"OnlyThisOne"}))
        default_guard = W0Guard()
        assert custom_guard.is_protected("BearerIntegrity") is False
        assert custom_guard.is_protected("OnlyThisOne") is True
        assert default_guard.is_protected("BearerIntegrity") is True
        assert default_guard.is_protected("OnlyThisOne") is False


# ---------------------------------------------------------------------------
# Sanity: the double-barrier design actually requires both checks
# ---------------------------------------------------------------------------

class TestBothBarriersIndependently:

    def test_write_blocked_by_registry_even_if_flag_were_somehow_false(self):
        """
        Construct a Weight registered under a canonical W0 name but force
        is_immutable=False past the registration guard (using the escape
        hatch documented above: object.__setattr__ to build a Weight
        directly, bypassing CriticalityMatrix.register() entirely). This
        simulates the exact desync W0Guard.enforce_write's registry check
        exists to catch, independent of the object's own flag.
        """
        m = CriticalityMatrix()
        # Bypass register()/enforce_registration by constructing the
        # Weight directly and inserting it into the matrix's private dict.
        rogue_weight = Weight(
            name="BearerIntegrity", value=1.0, baseline=1.0,
            is_immutable=False,  # deliberately desynced from the registry
        )
        m._weights["BearerIntegrity"] = rogue_weight

        # Weight.is_immutable is False, so nothing on the Weight object
        # itself would refuse this write — enforce_write's registry check
        # is the only thing left standing.
        with pytest.raises(ImmutableWeightViolation):
            m.update("BearerIntegrity", 0.0)

    def test_write_blocked_by_flag_even_for_non_registry_name(self):
        """Symmetric case: a weight NOT in W0_INVARIANT_NAMES but marked
        is_immutable=True must still be refused — the flag alone is
        sufficient, the name registry isn't the only path either."""
        m = CriticalityMatrix()
        m.register("SomeCustomInvariant", value=1.0, is_immutable=True)
        with pytest.raises(ImmutableWeightViolation):
            m.update("SomeCustomInvariant", 0.0)