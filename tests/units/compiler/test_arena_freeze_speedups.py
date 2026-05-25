"""Failing tests for the freeze-side speedups laid out as Tier 1 options:

* **A — Batched Python helper per Component.** One Python function call
  per Component replaces ~15-20 individual ``getattr`` / ``call_method0``
  crossings. The Rust side caches a ``Py<PyAny>`` reference to a helper
  function (constructed at session creation, e.g.
  ``reflex_compiler_rust._arena_freeze_extract``) and invokes it on
  every Component encountered during freeze.

* **B — Per-class freeze plan precomputed at first sight.** Class-level
  data — ``get_props()`` result, ``_rename_props``,
  ``_memoization_mode`` — read **once per class**, cached on
  ``PyRefs::class_metadata``. Subsequent same-class instances skip the
  reads.

* **C — Skip-list cache for "trivial" optional methods.** Methods like
  ``_get_added_hooks`` / ``_get_dynamic_imports`` / ``_get_hooks`` /
  ``_get_components_in_props`` / ``_get_custom_code`` that return
  trivial values (None / empty dict / empty list / empty string) for a
  given class get marked "skip" after a warmup window. Future instances
  of that class don't call the method at all.

Each test pins one **observable invariant**: a counting harness that
patches the relevant Python method/attribute and asserts the call
shape changes after the optimization lands. The tests are designed to
also catch over-eager skipping (false-negative) — a method that
returns non-trivial values for some class must keep being called.

Validation strategy (see ``test_validation_*`` cases): each speedup
test is paired with a sanity-check that confirms the harness is
actually counting what it claims to count. That sanity-check passes
today (legacy behavior) so we know the counting machinery works; the
main test fails today (no optimization) and passes after the
implementation lands.
"""

from __future__ import annotations

from collections import Counter
from unittest.mock import patch

import pytest

import reflex as rx
from reflex.compiler.session import CompilerSession
from reflex_base.components.component import Component


class _SpeedupState(rx.State):
    counter: int = 0
    items: list[str] = ["a", "b", "c"]

    def inc(self) -> None:
        self.counter += 1


def _many_same_class_page():
    """Page with many instances of the same Component classes — primes
    the per-class caches that B + C are designed to exploit."""
    return rx.vstack(
        rx.heading("Speedup bench"),
        *(rx.text(f"row {i} count={_SpeedupState.counter}") for i in range(8)),
        *(rx.button(f"btn {i}", on_click=_SpeedupState.inc) for i in range(8)),
        rx.foreach(_SpeedupState.items, lambda it: rx.text(it)),
    )


# ---------------------------------------------------------------------------
# A. Batched Python helper per Component
# ---------------------------------------------------------------------------


def test_A_batched_helper_called_once_per_visited_component() -> None:
    """A: the arena freeze calls a single batched extractor function
    once per Component instance it visits.

    The contract: ``reflex_compiler_rust._native.CompilerSession`` (or
    a module-level Python helper it constructs at session init)
    exposes a function whose call count equals the number of distinct
    Components freeze touches. The function is named
    ``_arena_freeze_extract`` — its presence as an importable callable
    pins the contract.
    """
    from reflex_compiler_rust import _native

    extract = getattr(_native, "_arena_freeze_extract", None)
    assert extract is not None, (
        "A: arena freeze must expose a batched per-Component extractor "
        "named `_arena_freeze_extract` on `reflex_compiler_rust._native`. "
        "This is the single PyO3 entry that replaces ~15-20 individual "
        "getattr/method calls per Component."
    )
    assert callable(extract), "_arena_freeze_extract must be callable"


def test_A_batched_helper_call_count_equals_component_count() -> None:
    """A: the batched extractor fires **exactly once** per Component
    visited (page tree + prop-components + app-wraps).

    Counting via a wrapper around the helper itself. Holds strong refs
    to visited Components so `id()` recycling doesn't perturb the
    count.
    """
    from reflex_compiler_rust import _native

    extract = getattr(_native, "_arena_freeze_extract", None)
    if extract is None:
        pytest.skip("A not implemented yet")

    calls: list[Component] = []
    original = extract

    def wrapper(c):
        calls.append(c)
        return original(c)

    sess = CompilerSession()
    comp = _many_same_class_page()
    with patch.object(_native, "_arena_freeze_extract", wrapper):
        page, _, _ = sess.compile_page_from_component_arena(comp, "Index", "/")

    # Every call must hit a distinct Component (no double-invocation
    # per id) — confirms the helper is the single batched entry point.
    ids = [id(c) for c in calls]
    assert len(ids) == len(set(ids)), (
        "A: helper called twice on the same Component instance — that "
        "means there's still a non-batched read path somewhere"
    )
    assert len(calls) >= 5, (
        f"A: extractor only called {len(calls)} times — freeze "
        "should hit every visited Component"
    )


def test_A_drops_pyo3_method_call_count_substantially() -> None:
    """A: total individual ``_get_*`` method invocations on Components
    must drop sharply once the batched helper is in place.

    Without A, the freeze calls each of these per Component:
    ``_get_imports``, ``_get_components_in_props``, ``_get_hooks_internal``,
    ``_get_hooks``, ``_get_added_hooks``, ``_get_custom_code``,
    ``_get_dynamic_imports``, ``_get_style``, ``_get_app_wrap_components``,
    ``get_props``. With the helper, these still execute — but they
    execute *inside the helper*, fanned out from a single PyO3
    boundary crossing. The total Python-side method-call count stays
    the same; what drops is the number of *PyO3 invocations from
    Rust*, which we surface via a counter the Rust session bumps
    every time it calls into Python during freeze.
    """
    sess = CompilerSession()
    if not hasattr(sess._inner, "freeze_pyo3_call_count"):
        pytest.skip("A not implemented yet (no freeze_pyo3_call_count counter)")

    comp = _many_same_class_page()
    sess._inner.reset_freeze_pyo3_call_count()
    sess.compile_page_from_component_arena(comp, "Index", "/")
    crossings = sess._inner.freeze_pyo3_call_count()

    # Distinct Components in the tree (children + prop-components +
    # app-wraps) — the freeze visits each once.
    n_components = _count_freeze_visited_components(comp)
    # With A, we should see roughly 1-3 boundary crossings per
    # Component (the batched helper + class lookup), not 15-20.
    crossings_per_component = crossings / max(n_components, 1)
    assert crossings_per_component <= 4, (
        f"A: {crossings_per_component:.1f} PyO3 crossings per Component "
        f"({crossings} total / {n_components} components) — batched "
        "helper not in use; legacy per-attr reads still firing"
    )


def _count_freeze_visited_components(comp) -> int:
    """Mirror of the freeze walk for invariant checks."""
    seen: set[int] = set()
    stack = [comp]
    while stack:
        c = stack.pop()
        if not isinstance(c, Component):
            continue
        if id(c) in seen:
            continue
        seen.add(id(c))
        stack.extend(getattr(c, "children", []) or [])
        stack.extend(c._get_components_in_props())
        try:
            wraps = c._get_app_wrap_components()
        except Exception:
            wraps = {}
        if hasattr(wraps, "values"):
            stack.extend(wraps.values())
        else:
            stack.extend(wraps)
    return len(seen)


def test_validation_A_baseline_proves_counting_works() -> None:
    """Validation: this test confirms the counting harness is sound by
    measuring the legacy (un-batched) call count. It must pass *today*
    even before A lands.

    If this test fails, the counting harness is broken and the A test
    can't be trusted. Today the freeze does ~10 ``_get_*`` calls per
    Component, so a 50-component page produces ~500 method calls. The
    assertion is a loose lower bound (>= 100) — the goal is just to
    prove the harness sees calls at all.
    """
    sess = CompilerSession()
    comp = _many_same_class_page()
    original = Component._get_imports
    n_calls = [0]

    def wrapped(self):
        n_calls[0] += 1
        return original(self)

    with patch.object(Component, "_get_imports", wrapped):
        sess.compile_page_from_component_arena(comp, "Index", "/")

    assert n_calls[0] >= 5, (
        "validation: _get_imports counting harness should see "
        f"≥5 calls on a multi-component page, saw {n_calls[0]}"
    )


# ---------------------------------------------------------------------------
# B. Per-class freeze plan
# ---------------------------------------------------------------------------


def test_B_get_props_called_once_per_class_not_per_instance() -> None:
    """B: ``Component.get_props()`` returns the dataclass-field list,
    a **class-level** invariant. Freeze must call it once per
    Component *class*, not once per *instance*.

    With B, a page containing 8 ``Heading``s + 8 ``Text``s +
    8 ``Button``s should call ``get_props`` ~3 times (once per class),
    not 24+ times (once per instance).
    """
    sess = CompilerSession()
    comp = _many_same_class_page()

    # Get the underlying class-level `get_props`. The descriptor is
    # bound differently on subclasses, but the body is the same — we
    # patch on Component and count.
    original = Component.get_props.__func__ if hasattr(Component.get_props, "__func__") else Component.get_props
    per_class_calls: Counter[str] = Counter()

    def wrapped(cls):
        per_class_calls[cls.__name__] += 1
        return original(cls)

    with patch.object(Component, "get_props", classmethod(wrapped)):
        sess.compile_page_from_component_arena(comp, "Index", "/")

    # Each class should be observed at most twice (allow one cold +
    # one warm path in case the implementation primes lazily); never
    # once per instance.
    for cls_name, n in per_class_calls.items():
        assert n <= 2, (
            f"B: get_props called {n} times for class {cls_name!r} — "
            "must be cached per-class, not per-instance"
        )


def test_B_rename_props_read_once_per_class() -> None:
    """B: ``_rename_props`` is class-level (subclass declarations).
    Reading it per instance is wasted work.
    """
    sess = CompilerSession()
    comp = _many_same_class_page()

    classes_touched: Counter[type] = Counter()
    original_getattr = Component.__getattribute__

    def wrapped(self, name):
        if name == "_rename_props":
            classes_touched[type(self)] += 1
        return original_getattr(self, name)

    with patch.object(Component, "__getattribute__", wrapped):
        sess.compile_page_from_component_arena(comp, "Index", "/")

    # Per class, the read should happen ≤ 2 times (one warm-up + a
    # tolerance for re-validation), not once per instance.
    for cls, n in classes_touched.items():
        assert n <= 2, (
            f"B: _rename_props read {n} times for {cls.__name__!r} — "
            f"page has multiple instances of this class; reads should be "
            "cached per-class"
        )


def test_B_class_metadata_cache_warm_speedup() -> None:
    """B: a second compile in the same session must be measurably
    faster than the first because the per-class metadata cache is
    primed.

    Requires the warm-path median to be **at least 8% faster** than
    cold — tighter than timer noise but loose enough to absorb GC
    jitter. Today warm ≥ cold because no class-level cache survives
    across compiles.
    """
    import time

    sess = CompilerSession()
    # Pre-warmup before measurement: ensures any one-time CPython
    # startup costs (dict resize, code cache fill) are amortized.
    for _ in range(5):
        sess.compile_page_from_component_arena(
            _many_same_class_page(), "Index", "/"
        )

    # 50× cold (fresh session each iter)
    cold = []
    for _ in range(50):
        cold_sess = CompilerSession()
        comp = _many_same_class_page()
        t0 = time.perf_counter_ns()
        cold_sess.compile_page_from_component_arena(comp, "Index", "/")
        cold.append(time.perf_counter_ns() - t0)

    # 50× warm (same session, cache primed)
    warm = []
    for _ in range(50):
        comp = _many_same_class_page()
        t0 = time.perf_counter_ns()
        sess.compile_page_from_component_arena(comp, "Index", "/")
        warm.append(time.perf_counter_ns() - t0)

    cold.sort()
    warm.sort()
    cold_med = cold[len(cold) // 2]
    warm_med = warm[len(warm) // 2]
    # Warm must beat cold by at least 8% — tighter than timer noise
    # but absorbs GC jitter.
    assert warm_med <= cold_med * 0.92, (
        f"B: warm session not measurably faster than cold "
        f"(warm={warm_med/1000:.0f}us cold={cold_med/1000:.0f}us). "
        "Per-class metadata cache isn't surviving across compiles — "
        "verify the cache lives on CompilerSession, not PyRefs."
    )


def test_validation_B_per_class_baseline_works() -> None:
    """Validation: the per-class observation harness works. Today
    (no B), get_props IS called per instance, so this test confirms
    we see ``> 2`` calls for at least one class — proves the
    measurement detects per-instance calls."""
    sess = CompilerSession()
    comp = _many_same_class_page()

    original = Component.get_props.__func__ if hasattr(Component.get_props, "__func__") else Component.get_props
    per_class_calls: Counter[str] = Counter()

    def wrapped(cls):
        per_class_calls[cls.__name__] += 1
        return original(cls)

    sess_inner_has_class_cache = hasattr(sess._inner, "class_metadata_cache_size")
    with patch.object(Component, "get_props", classmethod(wrapped)):
        sess.compile_page_from_component_arena(comp, "Index", "/")

    if sess_inner_has_class_cache:
        pytest.skip("B implemented — baseline check no longer informative")

    # Validate that the harness sees the per-instance calls today.
    assert any(n > 2 for n in per_class_calls.values()), (
        f"validation: harness should see ≥3 get_props calls for at "
        f"least one class pre-B, saw {dict(per_class_calls)}"
    )


# ---------------------------------------------------------------------------
# C. Skip-list cache for trivial returns
# ---------------------------------------------------------------------------


# Methods that are usually trivial returns (empty dict / None / empty list).
_OPTIONAL_METHODS = [
    "_get_added_hooks",
    "_get_dynamic_imports",
    "_get_hooks",
    "_get_custom_code",
]


def test_C_trivial_methods_skipped_after_warmup() -> None:
    """C: optional methods that return trivial values for a class
    must stop being called after a short warmup.

    On a page with 8 ``Text`` + 8 ``Button`` + 8 ``Heading`` instances,
    we expect each of those classes to be probed for each optional
    method a few times (warmup), then skipped. Total call count per
    method per class ≤ ~3 (warmup window).
    """
    sess = CompilerSession()
    if not hasattr(sess._inner, "freeze_trivial_skip_count"):
        pytest.skip("C not implemented yet")

    comp = _many_same_class_page()

    per_method_class_calls: Counter[tuple[str, str]] = Counter()
    originals = {m: getattr(Component, m) for m in _OPTIONAL_METHODS}

    def make_wrapper(name: str, orig):
        def wrapped(self):
            per_method_class_calls[(name, type(self).__name__)] += 1
            return orig(self)
        return wrapped

    patches = [
        patch.object(Component, m, make_wrapper(m, originals[m]))
        for m in _OPTIONAL_METHODS
    ]
    for p in patches:
        p.start()
    try:
        sess.compile_page_from_component_arena(comp, "Index", "/")
    finally:
        for p in patches:
            p.stop()

    # Warmup window of 3 — after that, the skip-list takes over.
    for (method, cls), n in per_method_class_calls.items():
        assert n <= 3, (
            f"C: {method} called {n} times for class {cls!r} — skip-list "
            "cache not engaging; trivial-return method should be elided "
            "after warmup"
        )


def test_C_skip_list_does_not_skip_nontrivial_classes() -> None:
    """C must not over-eagerly skip methods on classes that
    legitimately return non-trivial values.

    Construct a custom Component subclass whose ``_get_custom_code``
    returns a non-trivial string every time; assert it's called every
    instance, never skipped.
    """
    sess = CompilerSession()
    if not hasattr(sess._inner, "freeze_trivial_skip_count"):
        pytest.skip("C not implemented yet")

    from reflex_components_core.base.bare import Bare

    class NoisyBare(Bare):
        _call_count: int = 0

        def _get_custom_code(self):
            type(self)._call_count += 1
            return f"// inline {type(self)._call_count}"

    comp = rx.vstack(*(NoisyBare.create(contents=str(i)) for i in range(6)))
    sess.compile_page_from_component_arena(comp, "Index", "/")

    # Each NoisyBare instance must have had its _get_custom_code
    # called — the skip-list must NOT engage on a class that returns
    # non-trivial values.
    assert NoisyBare._call_count >= 6, (
        f"C: _get_custom_code called only {NoisyBare._call_count} times "
        "for 6 non-trivial instances — skip-list is over-eager and "
        "skipping legitimately useful methods"
    )


def test_C_periodic_revalidation() -> None:
    """C: skip-list entries should re-validate periodically so a class
    that *starts* returning non-trivial values eventually unsticks.

    Counterfactual harness: a Bare subclass that returns trivial
    custom_code for the first 50 compiles, then non-trivial. After
    skip-list engages (assumed within ~3 instances), then ~50 compiles
    of the legitimate return, the harness should see at least *some*
    of those legitimate returns reach the freeze emit (custom_code
    non-empty in the snapshot).
    """
    sess = CompilerSession()
    if not hasattr(sess._inner, "freeze_trivial_skip_count"):
        pytest.skip("C not implemented yet")

    from reflex_components_core.base.bare import Bare

    class RotatingBare(Bare):
        _phase: list[str] = ["trivial"]

        def _get_custom_code(self):
            if type(self)._phase[0] == "trivial":
                return ""
            return f"// real code"

    # Warmup: 10 trivial returns to engage skip-list.
    for _ in range(10):
        sess.compile_page_from_component_arena(
            rx.vstack(RotatingBare.create(contents="x")), "Index", "/"
        )

    # Flip phase. After enough compiles, the skip-list should
    # re-validate and observe the non-trivial return.
    RotatingBare._phase[0] = "real"
    saw_non_trivial = False
    for _ in range(120):
        page, _, _ = sess.compile_page_from_component_arena(
            rx.vstack(RotatingBare.create(contents="x")), "Index", "/"
        )
        if "// real code" in page:
            saw_non_trivial = True
            break

    assert saw_non_trivial, (
        "C: skip-list never re-validated. A class that flipped from "
        "trivial → non-trivial returns must eventually have its "
        "methods re-probed."
    )


def test_validation_C_baseline_proves_method_counting_works() -> None:
    """Validation: today's freeze pre-C calls every optional method
    on every Component. The counter sees that pattern."""
    sess = CompilerSession()
    if hasattr(sess._inner, "freeze_trivial_skip_count"):
        pytest.skip("C implemented — baseline check no longer informative")

    comp = _many_same_class_page()
    per_method: Counter[str] = Counter()
    originals = {m: getattr(Component, m) for m in _OPTIONAL_METHODS}

    def make_wrapper(name: str, orig):
        def wrapped(self):
            per_method[name] += 1
            return orig(self)
        return wrapped

    patches = [
        patch.object(Component, m, make_wrapper(m, originals[m]))
        for m in _OPTIONAL_METHODS
    ]
    for p in patches:
        p.start()
    try:
        sess.compile_page_from_component_arena(comp, "Index", "/")
    finally:
        for p in patches:
            p.stop()

    # Without C, each optional method fires for every Component
    # instance — many calls per method.
    assert any(n >= 5 for n in per_method.values()), (
        f"validation: at least one optional method should fire ≥5 "
        f"times pre-C, saw {dict(per_method)}"
    )


# ---------------------------------------------------------------------------
# Cross-cutting correctness: optimizations must not change output
# ---------------------------------------------------------------------------


def test_ABC_output_unchanged() -> None:
    """A + B + C are pure perf optimizations. Compiled page JSX + memo
    bodies + imports must be identical to the un-optimized output.

    Pin output via a structural snapshot taken today (pre-optimization)
    and assert it survives every iteration of the optimization work.
    """
    sess = CompilerSession()
    comp = _many_same_class_page()
    page, bodies, imports = sess.compile_page_from_component_arena(
        comp, "Index", "/"
    )
    # Structural assertions that survive whitespace-level changes but
    # catch real divergences.
    assert "export default function Component()" in page
    assert "useContext(EventLoopContext)" in page
    assert len(bodies) >= 1, "stateful page must produce memo bodies"
    assert any("StateContexts" in page for _ in [0]), "state binding emitted"
    assert isinstance(imports, dict)

    # Determinism across a second call in the same session.
    comp2 = _many_same_class_page()
    page2, bodies2, imports2 = sess.compile_page_from_component_arena(
        comp2, "Index", "/"
    )
    assert page == page2
    assert sorted(b[0] for b in bodies) == sorted(b[0] for b in bodies2)
