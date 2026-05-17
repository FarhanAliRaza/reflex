"""Single-page microbenchmark for the run-rust pipeline.

Builds **one** feature-rich page (state, vars, foreach, cond, match,
event handlers, markdown — all the stuff that creates memo candidates +
add_imports overrides), then runs the actual compile_pages flow with
per-phase timers labeled Python / Rust / Hybrid so we know exactly
which work is Python-bound and which is in the Rust extension.

Each phase is timed inside an instrumented copy of
``reflex.compiler.rust_pipeline.compile_pages``'s page loop — same code
path the CLI runs, just with ``perf_counter_ns`` around each step.

Usage:
    uv run python scripts/benchmark_single_page.py [runs]

Default: 10 runs. First run is treated as a warmup and excluded from
the aggregate so the per-component ``_imports_cache`` doesn't make
subsequent runs look artificially cheap.
"""

from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


def _ns() -> int:
    return time.perf_counter_ns()


def _ms(ns: int | float) -> float:
    return ns / 1_000_000


# ---------------------------------------------------------------------------
# Synthetic page
# ---------------------------------------------------------------------------


def _build_app(scale: int = 1):
    """One page exercising the surfaces compile_pages touches.

    Args:
        scale: how many "section" blocks to repeat. ``scale=1`` is the
            ~47-node baseline; each extra unit adds ~80 nodes.

    Returns:
        A loaded ``rx.App`` with a single ``/bench`` route registered.
    """
    import reflex as rx

    class BenchState(rx.State):
        items: list[str] = [f"item-{i}" for i in range(20)]
        counter: int = 0
        current_key: str = "k1"

        @rx.event
        def increment(self) -> None:
            self.counter += 1

        @rx.event
        def zero_counter(self) -> None:
            self.counter = 0

    def row(item: rx.Var) -> rx.Component:
        return rx.hstack(
            rx.text(item),
            rx.button("inc", on_click=BenchState.increment),
            rx.button("reset", on_click=BenchState.zero_counter),
        )

    def section() -> rx.Component:
        return rx.vstack(
            rx.heading("Microbench page", size="3"),
            rx.text(f"counter: {BenchState.counter}"),
            rx.markdown(
                "# header\n\nSome **markdown** with `code` and a [link](https://x)."
            ),
            rx.cond(
                BenchState.counter > 0,
                rx.box(rx.text("positive"), rx.button("more")),
                rx.box(rx.text("non-positive"), rx.button("kick")),
            ),
            rx.match(
                BenchState.current_key,
                ("k1", rx.text("key 1 active")),
                ("k2", rx.text("key 2 active")),
                rx.text("default"),
            ),
            rx.foreach(BenchState.items, row),
            rx.hstack(
                rx.button("global inc", on_click=BenchState.increment),
                rx.button("global reset", on_click=BenchState.zero_counter),
            ),
        )

    def page() -> rx.Component:
        return rx.vstack(*[section() for _ in range(scale)])

    app = rx.App()
    app.add_page(page, route="/bench")
    return app


# ---------------------------------------------------------------------------
# Phase timer
# ---------------------------------------------------------------------------


class PhaseTimer:
    """Accumulates per-phase nanosecond durations across runs.

    Phases are tagged ``python``, ``rust``, or ``hybrid`` (Rust walk
    that calls back into Python). The summary makes the runtime split
    explicit.
    """

    KIND_ORDER = {"python": 0, "hybrid": 1, "rust": 2}

    def __init__(self, sub: SubTimer | None = None) -> None:
        self.samples: dict[str, list[int]] = {}
        self.kinds: dict[str, str] = {}
        self.order: list[str] = []
        self._sub = sub

    def attach_sub(self, sub: SubTimer | None) -> None:
        self._sub = sub

    @contextmanager
    def measure(self, name: str, kind: str = "python"):
        if name not in self.kinds:
            self.kinds[name] = kind
            self.order.append(name)
        if self._sub is not None:
            self._sub.push_parent(name)
        t0 = _ns()
        try:
            yield
        finally:
            self.samples.setdefault(name, []).append(_ns() - t0)
            if self._sub is not None:
                self._sub.pop_parent()

    def trim_warmup(self) -> None:
        """Discard the first sample of every phase (the cold-cache run)."""
        for name in self.samples:
            if len(self.samples[name]) > 1:
                self.samples[name] = self.samples[name][1:]

    def report(self, runs: int) -> None:
        per_run_medians: list[tuple[str, float, str]] = []
        kind_run_totals = {"python": 0.0, "hybrid": 0.0, "rust": 0.0}

        header = (
            f"{'phase':<46}{'kind':<8}"
            f"{'median':>9}{'mean':>9}{'p95':>9}{'min':>9}{'max':>9}"
        )
        print(header)
        print(f"{'':<46}{'':<8}{'(ms)':>9}{'(ms)':>9}{'(ms)':>9}{'(ms)':>9}{'(ms)':>9}")
        print("-" * len(header))

        for name in self.order:
            samples = [s / 1_000_000 for s in self.samples[name]]
            median = statistics.median(samples)
            mean = statistics.mean(samples)
            p95 = _p95(samples)
            mn = min(samples)
            mx = max(samples)
            kind = self.kinds[name]
            per_run_medians.append((name, median, kind))
            kind_run_totals[kind] += median
            print(
                f"{name:<46}{kind:<8}"
                f"{median:>9.3f}{mean:>9.3f}{p95:>9.3f}{mn:>9.3f}{mx:>9.3f}"
            )

        per_run_median_total = sum(m for _, m, _ in per_run_medians)
        print("-" * len(header))
        print(f"{'Per-run median total:':<54}{per_run_median_total:>9.3f}  ms")
        print()
        print("Breakdown by where the work actually runs (median per run):")
        for kind in ("python", "hybrid", "rust"):
            t = kind_run_totals[kind]
            pct = (t / per_run_median_total * 100) if per_run_median_total else 0
            label = {
                "python": "Python only",
                "hybrid": "Rust + PyO3 callbacks",
                "rust":   "pure Rust (no callbacks)",
            }[kind]
            print(f"  {label:<28}{t:>8.2f} ms  ({pct:5.1f}%)")
        print()
        print(f"Runs aggregated: {runs} (1 warmup discarded)")


def _p95(samples: list[float]) -> float:
    if not samples:
        return 0.0
    s = sorted(samples)
    return s[int(0.95 * (len(s) - 1))]


# ---------------------------------------------------------------------------
# Sub-phase timer — accumulates monkey-patched fine-grained timings
# alongside the coarse PhaseTimer. Each sub-phase belongs to a parent
# (matches a row in PhaseTimer) so the printer can render a nested
# breakdown that reconciles against the parent total.
# ---------------------------------------------------------------------------


class SubTimer:
    """Per-run accumulator for sub-phase timings + counters.

    Each parent phase has its own dict of sub-names. Patched functions
    call ``add_ns(sub_name, ns)`` and ``add_count(name)`` without
    specifying a parent — the SubTimer maintains a parent stack
    (pushed/popped by :meth:`PhaseTimer.measure`) so the topmost active
    wrapper receives the attribution. A function called from two
    different parent wrappers (e.g. ``_get_all_custom_code`` invoked by
    both the page wrapper and ``app_root composition + render``) gets
    its time correctly split.

    All sub-phase timings are **self-time only** — patched functions
    reimplement their bodies so recursive child work flows into the
    child level's own timing rather than the parent's inclusive measure.
    """

    def __init__(self) -> None:
        # parent -> sub_name -> per-run total ns (one int per run)
        self.run_totals: dict[str, dict[str, list[int]]] = {}
        # parent -> counter_name -> per-run total (one int per run)
        self.run_counts: dict[str, dict[str, list[int]]] = {}
        # Mutable in-run accumulator; reset each run.
        self._current_ns: dict[str, dict[str, int]] = {}
        self._current_count: dict[str, dict[str, int]] = {}
        # Active-parent stack updated by PhaseTimer.measure.
        self._parent_stack: list[str] = []
        # Preserve insertion order for the printer.
        self.parent_order: list[str] = []
        self.sub_order: dict[str, list[str]] = {}
        self.count_order: dict[str, list[str]] = {}

    def push_parent(self, name: str) -> None:
        self._parent_stack.append(name)

    def pop_parent(self) -> None:
        if self._parent_stack:
            self._parent_stack.pop()

    def begin_run(self) -> None:
        self._current_ns = {}
        self._current_count = {}

    def _active_parent(self) -> str | None:
        return self._parent_stack[-1] if self._parent_stack else None

    def add_ns(self, sub: str, ns: int) -> None:
        parent = self._active_parent()
        if parent is None:
            return
        if parent not in self.parent_order:
            self.parent_order.append(parent)
        sub_list = self.sub_order.setdefault(parent, [])
        if sub not in sub_list:
            sub_list.append(sub)
        bucket = self._current_ns.setdefault(parent, {})
        bucket[sub] = bucket.get(sub, 0) + ns

    def add_count(self, name: str, n: int = 1) -> None:
        parent = self._active_parent()
        if parent is None:
            return
        if parent not in self.parent_order:
            self.parent_order.append(parent)
        clist = self.count_order.setdefault(parent, [])
        if name not in clist:
            clist.append(name)
        bucket = self._current_count.setdefault(parent, {})
        bucket[name] = bucket.get(name, 0) + n

    def flush_run(self) -> None:
        for parent, subs in self._current_ns.items():
            tgt = self.run_totals.setdefault(parent, {})
            for sub, ns in subs.items():
                tgt.setdefault(sub, []).append(ns)
        for parent, counts in self._current_count.items():
            tgt = self.run_counts.setdefault(parent, {})
            for name, n in counts.items():
                tgt.setdefault(name, []).append(n)
        # Ensure every known (parent, sub) gets a zero sample for runs
        # where the wrapper wasn't hit — keeps medians honest.
        for parent in self.parent_order:
            tot = self.run_totals.setdefault(parent, {})
            cnts = self.run_counts.setdefault(parent, {})
            for sub in self.sub_order.get(parent, []):
                if len(tot.setdefault(sub, [])) < self._expected_run_count(tot):
                    tot[sub].append(0)
            for cname in self.count_order.get(parent, []):
                if len(cnts.setdefault(cname, [])) < self._expected_run_count(cnts):
                    cnts[cname].append(0)
        self._current_ns = {}
        self._current_count = {}

    @staticmethod
    def _expected_run_count(d: dict[str, list[int]]) -> int:
        return max((len(v) for v in d.values()), default=0)

    def trim_warmup(self) -> None:
        for subs in self.run_totals.values():
            for k in list(subs):
                if len(subs[k]) > 1:
                    subs[k] = subs[k][1:]
        for counts in self.run_counts.values():
            for k in list(counts):
                if len(counts[k]) > 1:
                    counts[k] = counts[k][1:]

    def parent_total_ms(self, parent: str) -> float:
        """Median sum-of-subs (ms) per run for ``parent``."""
        subs = self.run_totals.get(parent, {})
        if not subs:
            return 0.0
        # Aggregate per-run sums first, then take median.
        run_count = max(len(v) for v in subs.values())
        per_run = [
            sum(v[i] if i < len(v) else 0 for v in subs.values()) / 1_000_000
            for i in range(run_count)
        ]
        return statistics.median(per_run)

    def print_breakdown(self, phase_timer: PhaseTimer) -> None:
        if not self.parent_order:
            return
        print()
        print("=" * 90)
        print("PYTHON SUB-PHASE BREAKDOWN (monkey-patched per-step timers)")
        print("=" * 90)
        print(
            "Each sub-phase row reports the median per-run total for that"
            " specific call site."
        )
        print(
            "'driver' = parent wrapper time minus sum of timed sub-phases —"
            " unaccounted residual"
        )
        print(
            "(loop control, attribute reads, Python function-entry overhead)."
        )

        for parent in self.parent_order:
            subs = self.run_totals.get(parent, {})
            counts = self.run_counts.get(parent, {})
            if not subs and not counts:
                continue
            parent_total = (
                statistics.median(phase_timer.samples.get(parent, [0]))
                / 1_000_000
                if parent in phase_timer.samples
                else None
            )
            print()
            print(f"--- {parent} ---")
            if parent_total is not None:
                print(f"parent wrapper median:  {parent_total:.3f} ms")
            header = (
                f"  {'sub-phase':<42}{'median':>10}{'mean':>10}"
                f"{'p95':>10}{'share':>9}"
            )
            print(header)
            print(
                f"  {'':<42}{'(ms)':>10}{'(ms)':>10}{'(ms)':>10}{'':>9}"
            )
            print("  " + "-" * (len(header) - 2))
            sub_total = 0.0
            for sub in self.sub_order.get(parent, []):
                samples_ns = subs.get(sub, [])
                if not samples_ns:
                    continue
                ms_samples = [s / 1_000_000 for s in samples_ns]
                med = statistics.median(ms_samples)
                mean = statistics.mean(ms_samples)
                p95 = _p95(ms_samples)
                share = (
                    f"{(med / parent_total * 100):5.1f}%"
                    if parent_total
                    else "  n/a"
                )
                sub_total += med
                print(
                    f"  {sub:<42}{med:>10.3f}{mean:>10.3f}"
                    f"{p95:>10.3f}{share:>9}"
                )
            print("  " + "-" * (len(header) - 2))
            print(f"  {'sum of timed sub-phases:':<42}{sub_total:>10.3f}")
            if parent_total is not None:
                driver = parent_total - sub_total
                pct = (driver / parent_total * 100) if parent_total else 0
                kind = phase_timer.kinds.get(parent, "python")
                tag = "driver / unaccounted"
                # Hybrid / pure-Rust phases account for their work in
                # the Rust-side timing tables; Python-side sub-timers
                # only see the PyO3 wrappers if any. Don't warn on a
                # large residual there.
                if kind == "python" and abs(driver) > parent_total * 0.10:
                    tag += "  ⚠ >10% — add another sub-timer"
                elif kind != "python":
                    tag = "driver / Rust+PyO3 work (see Rust table)"
                print(
                    f"  {tag:<42}{driver:>10.3f}{'':>10}{'':>10}{pct:>8.1f}%"
                )

            # Counter / per-op rows.
            if counts:
                print()
                print(f"  {'counter':<42}{'median':>10}{'mean':>10}")
                print("  " + "-" * 64)
                for cname in self.count_order.get(parent, []):
                    csamples = counts.get(cname, [])
                    if not csamples:
                        continue
                    med = statistics.median(csamples)
                    mean = statistics.mean(csamples)
                    print(f"  {cname:<42}{med:>10.1f}{mean:>10.1f}")
                # Per-op µs cost rows for each sub × each counter (median).
                print()
                print(f"  {'per-op cost (median)':<42}{'µs/op':>10}")
                print("  " + "-" * 54)
                for sub in self.sub_order.get(parent, []):
                    sub_samples = subs.get(sub, [])
                    if not sub_samples:
                        continue
                    sub_med_ns = statistics.median(sub_samples)
                    for cname in self.count_order.get(parent, []):
                        cs = counts.get(cname, [])
                        if not cs:
                            continue
                        c_med = statistics.median(cs)
                        if c_med <= 0:
                            continue
                        per_op = sub_med_ns / c_med / 1000  # µs
                        label = f"{sub}  /  {cname}"
                        print(f"  {label:<42}{per_op:>10.3f}")


# ---------------------------------------------------------------------------
# Monkey-patches that feed the SubTimer with fine-grained timings for the
# hot Python phases identified by PROFILING_FINDINGS.md §9.
# ---------------------------------------------------------------------------


def _install_python_subtimers(sub: SubTimer) -> callable:
    """Patch hot Python phases to record into ``sub``.

    The patches replace module-level / class-level callables in
    ``reflex/`` and ``reflex_base/`` for the duration of the benchmark.
    Calls remain semantically identical — every wrapper just brackets the
    original with ``perf_counter_ns`` reads.

    Args:
        sub: the accumulator to feed.

    Returns:
        A zero-arg ``restore`` callable that puts every patched symbol
        back. Use it in a ``finally`` clause so failures don't leak the
        patches into other tests.
    """
    import copy

    import importlib

    # ``reflex.experimental.__init__`` re-exports ``memo`` as the
    # function (shadows the submodule attribute), so plain
    # ``import reflex.experimental.memo`` doesn't give us module access.
    memo_mod = importlib.import_module("reflex.experimental.memo")

    from reflex.compiler import compiler as compiler_mod
    from reflex.compiler import rust_memo
    from reflex_base.compiler import templates as templates_mod
    from reflex_base.components.component import Component

    # Capture originals.
    orig_walk = rust_memo.walk_and_memoize
    orig_wrap = rust_memo._wrap_with_memo
    orig_cppm = memo_mod.create_passthrough_component_memo
    orig_render = templates_mod._RenderUtils.render
    orig_render_tag = templates_mod._RenderUtils.render_tag
    orig_render_iter = templates_mod._RenderUtils.render_iterable_tag
    orig_render_match = templates_mod._RenderUtils.render_match_tag
    orig_render_cond = templates_mod._RenderUtils.render_condition_tag
    orig_custom_code = Component._get_all_custom_code
    orig_cup = compiler_mod.compile_unevaluated_page
    orig_into_component = compiler_mod.into_component
    orig_add_meta = compiler_mod.utils.add_meta
    # Fragment.create isn't patched; we call it directly inside patched_cup.

    # ---- walk_and_memoize ----
    # Reimplement to time self-work only. Recursive calls re-enter the
    # patched function so each level adds its own self-time. Parent
    # attribution is stack-based — whichever PhaseTimer.measure block is
    # currently active receives the records.

    def patched_walk(component, session, memo_bodies):
        from reflex_base.components.component import Component as _C

        if not isinstance(component, _C):
            return component
        sub.add_count("nodes_visited", 1)

        # Recurse children — re-enters this function; we do NOT time the
        # recursive call (would inclusively double-count subtree work).
        new_children = [patched_walk(c, session, memo_bodies) for c in component.children]
        if new_children != component.children:
            component.children = new_children

        t = _ns()
        decision = session.should_memoize(component)
        sub.add_ns("session.should_memoize", _ns() - t)

        if not decision:
            return component

        sub.add_count("wrappers_created", 1)
        # _wrap_with_memo is non-recursive but calls cppm; time them
        # separately so neither inclusively includes the other.
        return patched_wrap(component, memo_bodies)

    def patched_wrap(component, memo_bodies):
        import copy as _copy

        # Time create_passthrough_component_memo as its own sub-phase;
        # subtract from the wrap body so "wrap body (excl cppm)" reflects
        # the genuine non-cppm self-work.
        t = _ns()
        factory, definition = patched_cppm(component)
        # patched_cppm already recorded its own time; we don't re-record.

        t = _ns()
        export_name = definition.export_name
        if export_name not in memo_bodies:
            body = _copy.copy(definition.component)
            if definition.passthrough_hole_child is not None:
                body.children = [definition.passthrough_hole_child]
            memo_bodies[export_name] = (body, definition)
        wrapper = factory()
        if definition.passthrough_hole_child is not None:
            wrapper.children = list(component.children)
        sub.add_ns("_wrap_with_memo body (excl cppm)", _ns() - t)
        return wrapper

    def patched_cppm(component):
        t = _ns()
        try:
            return orig_cppm(component)
        finally:
            sub.add_ns("create_passthrough_component_memo", _ns() - t)

    rust_memo.walk_and_memoize = patched_walk
    rust_memo._wrap_with_memo = patched_wrap
    memo_mod.create_passthrough_component_memo = patched_cppm

    # ---- _get_all_custom_code on Component ----
    # Reimplement self-time-only: each leaf op gets timed; the recursive
    # `child._get_all_custom_code()` call re-enters the patched method,
    # which adds its own per-node self-time at that level.

    def patched_custom(self):
        sub.add_count("nodes_visited", 1)
        code: dict[str, None] = {}

        t = _ns()
        cc = self._get_custom_code()
        sub.add_ns("_get_custom_code", _ns() - t)
        if cc is not None:
            sub.add_count("nodes_with_code", 1)
            code[cc] = None

        t = _ns()
        prop_comps = list(self._get_components_in_props())
        sub.add_ns("_get_components_in_props", _ns() - t)
        for component in prop_comps:
            code |= component._get_all_custom_code()

        t = _ns()
        clzs = list(self._iter_parent_classes_with_method("add_custom_code"))
        sub.add_ns("_iter_parent_classes_with_method", _ns() - t)
        for clz in clzs:
            sub.add_count("parent_class_iters", 1)
            t = _ns()
            for item in clz.add_custom_code(self):
                code[item] = None
            sub.add_ns("parent.add_custom_code()", _ns() - t)

        for child in self.children:
            code |= child._get_all_custom_code()

        return code

    Component._get_all_custom_code = patched_custom

    # ---- _RenderUtils.render and render_tag ----
    # Reimplement self-time-only. Recursive helper calls (render_tag's
    # children loop, render_iterable_tag, render_match_tag,
    # render_condition_tag) each call back through `patched_render`, so
    # per-level self-time accumulates across recursion levels.

    def patched_render(component):
        if isinstance(component, str):
            sub.add_count("render_calls", 1)
            sub.add_count("render_string_branches", 1)
            return component or "null"

        sub.add_count("render_calls", 1)

        # Iterable / match / cond / contents branches: the helper itself
        # recurses through _RenderUtils.render. We let the patched render
        # see those recursive calls — no inclusive timing here.
        if "iterable" in component:
            sub.add_count("render_iterable_branches", 1)
            return orig_render_iter(component)
        if "match_cases" in component:
            sub.add_count("render_match_branches", 1)
            return orig_render_match(component)
        if "cond_state" in component:
            sub.add_count("render_cond_branches", 1)
            return orig_render_cond(component)
        if (contents := component.get("contents")) is not None:
            sub.add_count("render_contents_branches", 1)
            return contents or "null"
        return patched_render_tag(component)

    def patched_render_tag(component):
        sub.add_count("render_tag_calls", 1)
        t = _ns()
        name = component.get("name") or "Fragment"
        props = f"{{{','.join(component['props'])}}}"
        sub.add_ns("render_tag: props join", _ns() - t)

        rendered_children = [
            patched_render(child)
            for child in component.get("children", [])
            if child
        ]

        t = _ns()
        result = f"jsx({name},{props},{','.join(rendered_children)})"
        sub.add_ns("render_tag: format", _ns() - t)
        return result

    templates_mod._RenderUtils.render = staticmethod(patched_render)
    templates_mod._RenderUtils.render_tag = staticmethod(patched_render_tag)

    # ---- compile_unevaluated_page ----
    # Reimplementing the body lets us time each constituent call without
    # double-wrapping the whole function.

    def patched_cup(route, page, style=None, theme=None):
        from reflex_base.config import get_config
        from reflex_base.utils.format import make_default_page_title
        from reflex_components_core.base.fragment import Fragment as _Fragment

        try:
            t = _ns()
            component = orig_into_component(page.component)
            sub.add_ns("into_component", _ns() - t)

            t = _ns()
            component._add_style_recursive(style or {}, theme)
            sub.add_ns("_add_style_recursive", _ns() - t)

            t = _ns()
            component = _Fragment.create(component)
            sub.add_ns("Fragment.create", _ns() - t)

            meta_args = {
                "title": (
                    page.title
                    if page.title is not None
                    else make_default_page_title(get_config().app_name, route)
                ),
                "image": page.image,
                "meta": page.meta,
            }
            if page.description is not None:
                meta_args["description"] = page.description

            t = _ns()
            orig_add_meta(component, **meta_args)
            sub.add_ns("add_meta", _ns() - t)
        except Exception as e:
            if sys.version_info >= (3, 11):
                e.add_note(f"Happened while evaluating page {route!r}")
            raise
        else:
            return component

    compiler_mod.compile_unevaluated_page = patched_cup

    # Side-effect: `from reflex.compiler.compiler import compile_unevaluated_page`
    # in _instrumented_compile_pages was already bound before this patch ran.
    # We rely on the bench routing through the patched module attribute.
    # Force the bench's local import to use the patched version below.

    _ = copy  # silence unused

    def restore():
        rust_memo.walk_and_memoize = orig_walk
        rust_memo._wrap_with_memo = orig_wrap
        memo_mod.create_passthrough_component_memo = orig_cppm
        templates_mod._RenderUtils.render = staticmethod(orig_render)
        templates_mod._RenderUtils.render_tag = staticmethod(orig_render_tag)
        Component._get_all_custom_code = orig_custom_code
        compiler_mod.compile_unevaluated_page = orig_cup

    return restore


def _print_import_timing_table(sess) -> None:
    """Print the Rust-side ``collect_all_imports_into`` sub-breakdown.

    Pulls the thread-local snapshot from the **most recent** call into
    Rust — callers should run one fresh ``collect_all_imports_into`` just
    before invoking this so the counters reflect the page just walked
    rather than e.g. the memo-body walk that ran later.
    """
    t = sess._inner.last_import_timings_ns()
    walk_total = t.get("walk_total_ns", 0)
    spans = {
        k: v
        for k, v in t.items()
        if k.endswith("_ns") and k != "walk_total_ns"
    }
    counts = {
        k: v for k, v in t.items() if k.endswith("_count")
    }

    print()
    print("=" * 90)
    print("RUST-SIDE collect_all_imports_into BREAKDOWN")
    print("=" * 90)
    print(f"{'phase':<32}{'ns':>14}{'ms':>14}{'share':>10}")
    print("-" * 70)
    print(
        f"{'walk_total_ns':<32}{walk_total:>14}"
        f"{walk_total / 1e6:>14.3f}{'100.0%':>10}"
    )
    accounted = 0
    for k, v in sorted(spans.items(), key=lambda kv: kv[1], reverse=True):
        accounted += v
        share = (v / walk_total * 100) if walk_total else 0
        print(f"{'  ' + k:<32}{v:>14}{v / 1e6:>14.3f}{share:>9.1f}%")
    unaccounted = max(0, walk_total - accounted)
    upct = (unaccounted / walk_total * 100) if walk_total else 0
    print(
        f"{'  (unaccounted)':<32}{unaccounted:>14}"
        f"{unaccounted / 1e6:>14.3f}{upct:>9.1f}%"
    )

    print()
    print(f"{'counter':<32}{'count':>14}")
    print("-" * 46)
    for k, v in counts.items():
        print(f"{k:<32}{v:>14}")

    if counts.get("node_count", 0) and walk_total:
        print()
        print(f"per-node cost: {walk_total / counts['node_count']:.0f} ns")
    if counts.get("var_count", 0) and spans.get("get_imports_call_ns"):
        gic = spans["get_imports_call_ns"]
        print(
            f"get_imports_call_ns / node: "
            f"{gic / counts['node_count']:.0f} ns"
            if counts.get("node_count")
            else ""
        )


# ---------------------------------------------------------------------------
# Instrumented compile loop
# ---------------------------------------------------------------------------


def _instrumented_compile_pages(
    app, sess, timer: PhaseTimer, web_dir: Path, sub: SubTimer | None = None
) -> None:
    """Mirror of ``rust_pipeline.compile_pages`` with per-phase timers.

    Skips the post-loop static-artifact emission (``_emit_static_artifacts``,
    plugin pre-compile, custom-component re-emit) — those run once per
    compile regardless of page count, so the single-page benchmark
    focuses on the per-page path.

    Args:
        app: a loaded ``rx.App`` with at least one route.
        sess: the live ``CompilerSession`` shared across runs.
        timer: the accumulator for phase samples.
        web_dir: writable directory the rust emitters target.
        sub: optional sub-phase accumulator. When provided, the local
            ``component.render()`` vs ``_RenderUtils.render`` split is
            recorded into the ``app_root composition + render`` parent.
    """
    from reflex_base.compiler.templates import _render_hooks

    from reflex.compiler import compiler as legacy_compiler
    from reflex.compiler import rust_memo
    from reflex.compiler import utils as compiler_utils

    # Resolve the (possibly monkey-patched) module attribute at call time
    # so the SubTimer wrappers actually run.
    compile_unevaluated_page = legacy_compiler.compile_unevaluated_page
    walk_and_memoize = rust_memo.walk_and_memoize

    app._apply_decorated_pages()

    all_imports: dict[str, list] = {}
    memo_bodies: dict[str, object] = {}
    collected_app_wraps: dict[tuple[int, str], object] = {}

    for route, unev in app._unevaluated_pages.items():
        with timer.measure("compile_unevaluated_page", "python"):
            component = compile_unevaluated_page(route, unev, app.style, app.theme)

        with timer.measure("collect_all_imports_into", "hybrid"):
            sess.collect_all_imports_into(all_imports, component)

        with timer.measure("_get_all_app_wrap_components", "python"):
            collected_app_wraps.update(component._get_all_app_wrap_components())

        with timer.measure("walk_and_memoize", "python"):
            component = walk_and_memoize(component, sess, memo_bodies)

        with timer.measure("_get_all_custom_code", "python"):
            page_custom_code = list(component._get_all_custom_code())

        with timer.measure("_get_all_hooks + _render_hooks", "python"):
            page_hooks_body = _render_hooks(component._get_all_hooks())

        with timer.measure("compile_page_from_component (Rust JSX emit)", "hybrid"):
            rust_js = sess.compile_page_from_component(
                "Bench",
                component,
                route,
                custom_code=page_custom_code,
                hooks_body=page_hooks_body,
            )

        with timer.measure("page write_text", "python"):
            out_path = Path(compiler_utils.get_page_path(route))
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(rust_js)

    # Memo body emission — split into sub-phases so the Python vs Rust
    # split is legible.
    from reflex.compiler.rust_memo import _harvest_pre_hooks, _signature_for

    components_dir = Path(compiler_utils.get_memo_components_dir())
    components_dir.mkdir(parents=True, exist_ok=True)

    with timer.measure("memo body: collect_all_imports_into", "hybrid"):
        for body, _definition in memo_bodies.values():
            sess.collect_all_imports_into(all_imports, body)

    with timer.measure("memo body: _harvest_pre_hooks (Python walk)", "python"):
        prepared: list[tuple[str, str, object, str]] = []
        for name, (body, definition) in memo_bodies.items():
            prepared.append((
                name,
                _signature_for(definition),
                body,
                _harvest_pre_hooks(body),
            ))

    with timer.measure("memo body: compile_memo_from_component (Rust)", "hybrid"):
        emitted_js: list[tuple[str, str]] = []
        for name, signature, body, pre_hooks in prepared:
            js = sess.compile_memo_from_component(
                name, signature, body, pre_hooks=pre_hooks
            )
            emitted_js.append((name, js))

    with timer.measure("memo body: write_text", "python"):
        for name, js in emitted_js:
            (components_dir / f"{name}.jsx").write_text(js)

    # Keep the legacy `_get_all_imports` for app_root → ordered template
    # rendering. Time each constituent step inline so the sub-timer
    # report reconciles against the parent wrapper total.
    with timer.measure("app_root composition + render", "python"):
        from reflex_base.compiler.templates import _RenderUtils
        from reflex_base.config import get_config

        from reflex.compiler.compiler import (
            _apply_common_imports,
            _resolve_app_wrap_components,
            _resolve_radix_themes_plugin,
        )

        _record = (lambda name, dt: sub.add_ns(name, dt)) if sub else (lambda *_: None)

        t = _ns()
        _, radix_themes_plugin = _resolve_radix_themes_plugin(app, get_config().plugins)
        if radix_themes_plugin.enabled and radix_themes_plugin.theme is not None:
            collected_app_wraps[20, "Theme"] = radix_themes_plugin.theme
        app_wrappers = _resolve_app_wrap_components(app, collected_app_wraps)
        _record("plugin resolve + app_wrap resolve", _ns() - t)

        t = _ns()
        app_root = app._app_root(app_wrappers)
        _record("app._app_root(app_wrappers)", _ns() - t)

        t = _ns()
        sess.collect_all_imports_into(all_imports, app_root)
        _record("sess.collect_all_imports_into(app_root)", _ns() - t)

        t = _ns()
        app_root_imports = app_root._get_all_imports()
        _record("app_root._get_all_imports()", _ns() - t)

        t = _ns()
        _apply_common_imports(app_root_imports)
        _record("_apply_common_imports", _ns() - t)

        t = _ns()
        _ = "\n".join(
            _RenderUtils.get_import(m)
            for m in compiler_utils.compile_imports(app_root_imports)
        )
        _record("compile_imports + get_import join", _ns() - t)

        t = _ns()
        _ = "\n".join(app_root._get_all_custom_code())
        _record("app_root._get_all_custom_code() (full)", _ns() - t)

        t = _ns()
        hooks_dict = app_root._get_all_hooks()
        _record("app_root._get_all_hooks()", _ns() - t)
        t = _ns()
        _ = _render_hooks(hooks_dict)
        _record("_render_hooks", _ns() - t)

        # Split out the two halves of the render: Python Tag-tree
        # construction (component.render()) vs. stringification
        # (_RenderUtils.render).
        t = _ns()
        tag_tree = app_root.render()
        _record("component.render() (Tag tree build)", _ns() - t)
        t = _ns()
        _ = _RenderUtils.render(tag_tree)
        _record("_RenderUtils.render (top-level stringify)", _ns() - t)

        _ = legacy_compiler  # silence unused


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _setup_web_dir(tmp: Path) -> None:
    """Point Reflex at a writable tmp .web/ for this benchmark.

    Args:
        tmp: directory to use as ``REFLEX_ROOT``.
    """
    from reflex.utils import prerequisites

    web = tmp / ".web"
    web.mkdir(parents=True, exist_ok=True)
    # Monkey-patch get_web_dir so all compiler_utils paths land in tmp.
    prerequisites.get_web_dir = lambda: web  # type: ignore[assignment]


def _compare_python_vs_rust(app, sess, runs: int) -> None:
    """Head-to-head with **sub-step** timing on both paths.

    Each path is broken down into the discrete things it does so the
    exact source of the gap is visible — no assumptions.

    Args:
        app: a loaded ``rx.App`` with at least one route.
        sess: the live Rust ``CompilerSession``.
        runs: number of timed iterations (one warmup discarded).
    """
    from reflex.compiler import utils as compiler_utils
    from reflex.compiler.compiler import (
        _apply_common_imports,
        compile_unevaluated_page,
    )
    from reflex_base.compiler import templates as base_templates
    from reflex_base.compiler.templates import _render_hooks

    route, unev = next(iter(app._unevaluated_pages.items()))

    # Per-sub-step accumulators.
    py_steps: dict[str, list[int]] = {
        "_get_all_imports": [],
        "compile_imports (apply+sort)": [],
        "_get_all_dynamic_imports + sort": [],
        "_get_all_custom_code": [],
        "_get_all_hooks": [],
        "component.render() (recursive)": [],
        "page_template(...)": [],
    }
    rust_steps: dict[str, list[int]] = {
        "collect_all_imports_into (Rust+PyO3)": [],
        "_get_all_custom_code": [],
        "_get_all_hooks + _render_hooks": [],
        "compile_page_from_component (Rust+PyO3)": [],
    }

    for run_idx in range(runs + 1):
        # --- PYTHON PATH ---
        component_py = compile_unevaluated_page(route, unev, app.style, app.theme)

        t0 = _ns()
        imports = component_py._get_all_imports()
        t1 = _ns()
        _apply_common_imports(imports)
        compiled_imports = compiler_utils.compile_imports(imports)
        t2 = _ns()
        dynamic = sorted(component_py._get_all_dynamic_imports())
        t3 = _ns()
        custom = component_py._get_all_custom_code()
        t4 = _ns()
        hooks = component_py._get_all_hooks()
        t5 = _ns()
        rendered = component_py.render()
        t6 = _ns()
        _ = base_templates.page_template(
            imports=compiled_imports,
            dynamic_imports=dynamic,
            custom_codes=custom,
            hooks=hooks,
            render=rendered,
        )
        t7 = _ns()

        py_steps["_get_all_imports"].append(t1 - t0)
        py_steps["compile_imports (apply+sort)"].append(t2 - t1)
        py_steps["_get_all_dynamic_imports + sort"].append(t3 - t2)
        py_steps["_get_all_custom_code"].append(t4 - t3)
        py_steps["_get_all_hooks"].append(t5 - t4)
        py_steps["component.render() (recursive)"].append(t6 - t5)
        py_steps["page_template(...)"].append(t7 - t6)

        # --- RUST PATH ---
        component_rust = compile_unevaluated_page(route, unev, app.style, app.theme)

        t0 = _ns()
        page_imports: dict[str, list] = {}
        sess.collect_all_imports_into(page_imports, component_rust)
        t1 = _ns()
        page_custom_code = list(component_rust._get_all_custom_code())
        t2 = _ns()
        page_hooks_body = _render_hooks(component_rust._get_all_hooks())
        t3 = _ns()
        _ = sess.compile_page_from_component(
            "Bench",
            component_rust,
            route,
            custom_code=page_custom_code,
            hooks_body=page_hooks_body,
        )
        t4 = _ns()

        rust_steps["collect_all_imports_into (Rust+PyO3)"].append(t1 - t0)
        rust_steps["_get_all_custom_code"].append(t2 - t1)
        rust_steps["_get_all_hooks + _render_hooks"].append(t3 - t2)
        rust_steps["compile_page_from_component (Rust+PyO3)"].append(t4 - t3)

        if run_idx == 0:
            # Warmup samples tossed.
            for v in py_steps.values():
                v.pop()
            for v in rust_steps.values():
                v.pop()

    def _summary(steps: dict[str, list[int]], label: str) -> None:
        print()
        print(f"=== {label} ===")
        header = (
            f"{'step':<44}"
            f"{'median':>10}{'mean':>10}{'p95':>10}{'min':>10}{'max':>10}"
        )
        print(header)
        print(
            f"{'':<44}"
            f"{'(ms)':>10}{'(ms)':>10}{'(ms)':>10}{'(ms)':>10}{'(ms)':>10}"
        )
        print("-" * len(header))
        total = 0.0
        for name, ns_samples in steps.items():
            ms = [n / 1_000_000 for n in ns_samples]
            med = statistics.median(ms)
            total += med
            print(
                f"{name:<44}"
                f"{med:>10.3f}{statistics.mean(ms):>10.3f}"
                f"{_p95(ms):>10.3f}{min(ms):>10.3f}{max(ms):>10.3f}"
            )
        print("-" * len(header))
        print(f"{'Total (sum of medians):':<44}{total:>10.3f} ms")
        return total

    print()
    print("=" * 90)
    print("DETAILED PER-STEP COMPARISON")
    print("=" * 90)
    py_total = _summary(py_steps, "Python  _compile_page  — sub-steps")
    rust_total = _summary(rust_steps, "Rust    pipeline  — sub-steps")
    print()
    gap = rust_total - py_total
    pct = gap / py_total * 100 if py_total else 0
    print(
        f"Rust total {rust_total:.3f} ms  |  Python total {py_total:.3f} ms  "
        f"|  Gap = {gap:+.3f} ms  ({pct:+.1f}%)"
    )

    # Pull Rust-side phase timings from the most recent emit so we can
    # see WHERE inside compile_page_from_component the time actually
    # goes. Run one more compile to populate clean counters.
    component_last = compile_unevaluated_page(route, unev, app.style, app.theme)
    page_imports2: dict[str, list] = {}
    sess.collect_all_imports_into(page_imports2, component_last)
    page_custom_code2 = list(component_last._get_all_custom_code())
    page_hooks_body2 = _render_hooks(component_last._get_all_hooks())
    _ = sess.compile_page_from_component(
        "Bench",
        component_last,
        route,
        custom_code=page_custom_code2,
        hooks_body=page_hooks_body2,
    )
    rust_phases = sess.last_phase_timings_ns()

    print()
    print("=" * 90)
    print("RUST-SIDE PHASE BREAKDOWN (inside compile_page_from_component)")
    print("=" * 90)
    print("Last single compile, sampled from thread-local counters.")
    print()
    count_keys = {
        "node_count",
        "element_count",
        "var_count",
        "prop_count",
        "event_handler_count",
    }
    counts = {k: v for k, v in rust_phases.items() if k in count_keys}
    spans = {k: v for k, v in rust_phases.items() if k not in count_keys}

    total_ns = spans.get("read_page_total_ns", 0)
    emit_ns = spans.get("emit_ns", 0)
    sub_phases = [
        (k, v)
        for k, v in spans.items()
        if k not in ("read_page_total_ns", "emit_ns")
    ]
    sub_phases.sort(key=lambda kv: kv[1], reverse=True)

    print(f"{'phase':<32}{'ns':>14}{'ms':>14}")
    print("-" * 60)
    print(f"{'read_page_total_ns':<32}{total_ns:>14}{total_ns / 1e6:>14.3f}")
    print(f"{'  emit_ns (pure Rust)':<32}{emit_ns:>14}{emit_ns / 1e6:>14.3f}")
    for k, v in sub_phases:
        print(f"{'  ' + k:<32}{v:>14}{v / 1e6:>14.3f}")
    accounted = sum(v for _, v in sub_phases) + emit_ns
    unaccounted = max(0, total_ns - accounted)
    print(f"{'  (unaccounted)':<32}{unaccounted:>14}{unaccounted / 1e6:>14.3f}")

    print()
    print(f"{'counter':<32}{'count':>14}")
    print("-" * 46)
    for k in (
        "node_count",
        "element_count",
        "var_count",
        "prop_count",
        "event_handler_count",
    ):
        print(f"{k:<32}{counts.get(k, 0):>14}")

    # Per-call costs derived from the counts. These pinpoint *which*
    # individual operation is dominating once we know how many of each
    # we did.
    print()
    print("per-call costs (ns):")

    def percall(span_key: str, count_key: str) -> str:
        c = counts.get(count_key, 0)
        if not c:
            return "n/a"
        return f"{spans.get(span_key, 0) / c:.0f}"

    print(f"  class_name_ns / element        = {percall('class_name_ns', 'element_count')}")
    print(f"  resolve_tag_ns / element       = {percall('resolve_tag_ns', 'element_count')}")
    print(f"  import_alias_ns / element      = {percall('import_alias_ns', 'element_count')}")
    print(f"  get_props_call_ns / element    = {percall('get_props_call_ns', 'element_count')}")
    print(f"  children_attr_ns / element     = {percall('children_attr_ns', 'element_count')}")
    print(f"  event_triggers_attr_ns / elem  = {percall('event_triggers_attr_ns', 'element_count')}")
    print(f"  needs_ref_ns / element         = {percall('needs_ref_ns', 'element_count')}")
    print(f"  prop_value_getattr_ns / prop   = {percall('prop_value_getattr_ns', 'prop_count')}")
    print(f"  isinstance_var_ns / prop       = {percall('isinstance_var_ns', 'prop_count')}")
    print(f"  var_js_expr_attr_ns / var      = {percall('var_js_expr_attr_ns', 'var_count')}")
    print(f"  read_var_data_ns / var         = {percall('read_var_data_ns', 'var_count')}")


def benchmark(runs: int = 10, scale: int = 1) -> None:
    # CI=1 prevents reflex_enterprise auth gate in docs-style apps.
    os.environ.setdefault("CI", "1")
    os.environ.setdefault("REFLEX_TELEMETRY_ENABLED", "false")

    from reflex.compiler.session import CompilerSession

    sub = SubTimer()
    timer = PhaseTimer(sub=sub)

    with tempfile.TemporaryDirectory(prefix="reflex_bench_") as tmpstr:
        tmp = Path(tmpstr)
        _setup_web_dir(tmp)

        # Build the app once and the session once — exactly how the CLI
        # uses them across the page loop.
        app = _build_app(scale=scale)
        sess = CompilerSession()

        # Count the tree once for context.
        from reflex.compiler.compiler import compile_unevaluated_page

        first_route, first_unev = next(iter(app._unevaluated_pages.items()))
        evaluated = compile_unevaluated_page(
            first_route, first_unev, app.style, app.theme
        )
        node_count = _count_nodes(evaluated)
        print(f"Bench page: route={first_route!r}  tree={node_count} nodes")
        print(f"Runs: {runs} (1 warmup discarded)")
        print()

        # Install monkey-patches for fine-grained Python sub-timers.
        restore = _install_python_subtimers(sub)
        try:
            # Section 1: per-phase Rust-pipeline breakdown.
            for _ in range(runs + 1):
                sub.begin_run()
                _instrumented_compile_pages(app, sess, timer, tmp / ".web", sub)
                sub.flush_run()
        finally:
            restore()
        timer.trim_warmup()
        sub.trim_warmup()
        timer.report(runs)
        sub.print_breakdown(timer)

        # Surface the Rust-side collect_all_imports_into sub-table.
        # Drive a fresh single-page walk so the thread-local counters
        # snapshot reflects exactly one page's imports (mirrors the
        # per-page wrapper sample we report).
        all_imports_for_import_table: dict[str, list] = {}
        sess.collect_all_imports_into(all_imports_for_import_table, evaluated)
        _print_import_timing_table(sess)

        # Section 2: head-to-head Python vs Rust on the mechanical step.
        _compare_python_vs_rust(app, sess, runs)


def _count_nodes(comp) -> int:
    count = 1
    children = getattr(comp, "children", None) or []
    for child in children:
        try:
            count += _count_nodes(child)
        except Exception:
            count += 1
    return count


if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    scale = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    benchmark(runs=runs, scale=scale)
