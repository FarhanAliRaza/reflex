"""Python wrapper around the Rust ``CompilerSession``.

The Rust side (``reflex_compiler_rust._native.CompilerSession``) holds the
content-hash compile cache. The supported caller path is
:meth:`CompilerSession.compile_page_from_component_arena` — one PyO3
round-trip that freezes a Component tree into a ``Snapshot`` arena,
runs the in-Rust memoize pass, emits the page module + memo body
modules, and harvests page-level imports.

After PR6 (planx.md cutover deletion) the msgpack tree-IR entry
points are gone — there is no ``compile_page_ir``, ``compile_app_ir``,
or ``compile_page_from_bytes`` shim left. Static-artifact writers
(``compile_*_module``) and helper utilities
(``collect_all_imports``, ``should_memoize``, ``write_if_changed``,
``snapshot_stats``) stay.
"""

from __future__ import annotations

import importlib
from typing import Any

from reflex_base.utils.imports import ImportVar
from reflex_base.vars.base import Var, VarData
from reflex_components_core.base import Scripts
from reflex_components_core.base.document import Links, ScrollRestoration
from reflex_components_core.base.document import Meta as ReactMeta
from reflex_components_core.el.elements.metadata import Head, Link, Meta
from reflex_components_core.el.elements.other import Html
from reflex_components_core.el.elements.sectioning import Body

from reflex.utils.misc import preload_color_theme

_WHEEL_MISSING = (
    "reflex_compiler_rust wheel not available — install it via "
    "`maturin develop --release` in packages/reflex-compiler-rust."
)


class CompilerSession:
    """Long-lived compiler handle. Shared across hot-reloads.

    Constructing this is cheap (no compile work happens). The expensive piece
    is the underlying Rust ``CompilerSession`` which holds the content-hash
    cache across calls to :meth:`compile_page` / :meth:`compile_app`.
    """

    def __init__(self) -> None:
        """Initialize the Rust compiler session wrapper."""
        try:
            native_module = importlib.import_module("reflex_compiler_rust._native")
        except ImportError as exc:
            raise RuntimeError(_WHEEL_MISSING) from exc
        self._inner = native_module.CompilerSession()
        self._static_artifact_keys: dict[str, tuple[Any, ...]] = {}

    # ---- Cache controls -----------------------------------------------------

    def set_cache_capacity(self, cap: int | None) -> None:
        """Bound the in-process page-render cache. ``None`` for unbounded."""
        self._inner.set_cache_capacity(cap)

    def clear_cache(self) -> None:
        """Clear the in-process page-render cache."""
        self._inner.clear_cache()

    def cache_len(self) -> int:
        """Return the number of entries in the page-render cache.

        Returns:
            Cache entry count.
        """
        return int(self._inner.cache_len())

    # ---- Compile entry points ----------------------------------------------

    def compile_styles_root(self, stylesheets: list[str], out_path: str) -> None:
        """Write ``.web/styles/styles.css``.

        Ports :func:`reflex_base.compiler.templates.styles_template`.

        Args:
            stylesheets: stylesheet URLs spliced into ``@import url(...)``
                lines under the single ``@layer __reflex_base;`` header.
            out_path: absolute filesystem path.
        """
        self._inner.compile_styles_root(list(stylesheets), out_path)

    def compile_theme_from_component_arena(
        self, theme_component: object, out_path: str
    ) -> None:
        """Write ``.web/utils/theme.js`` directly from a theme Component.

        Replaces the
        ``theme_js = str(LiteralVar.create(theme_component))`` shuttle
        plus the old string-input ``compile_theme_module`` call: the
        theme Component now crosses the PyO3 boundary directly and the
        JS rendering happens on the Rust side.

        Args:
            theme_component: a Reflex Component instance representing
                the resolved theme (output of
                ``reflex.compiler.utils.create_theme(...)``).
            out_path: absolute filesystem path for the emitted module.
        """
        self._inner.compile_theme_from_component_arena(theme_component, out_path)

    def compile_app_root_arena(
        self,
        component: Any,
        import_window_libraries: str,
        window_imports: str,
        out_path: str,
    ) -> dict[str, list]:
        """Write ``.web/app/root.jsx`` directly from the app-root Component.

        Thin pass-through to the Rust PyO3 entry. The Rust side
        freezes the Component, harvests imports / custom_code / hooks
        / dynamic_imports / JSX render from the snapshot, formats the
        import block, and writes the file in one round-trip. The
        Python wrapper exists only so callers don't import the native
        module directly.

        Args:
            component: the resolved app-root Component (typically the
                output of ``app._app_root(app_wrappers)``).
            import_window_libraries: rendered ``import * as <alias>
                from "..."`` lines for bundled libraries; the caller
                still owns the bundled-libraries list since it lives
                in Python.
            window_imports: rendered ``"<path>": <alias>,`` entries
                that populate the global ``window["__reflex"]``
                mapping.
            out_path: absolute filesystem path for the emitted module.

        Returns:
            The harvested ``ParsedImportDict`` for the app-root tree
            (with ``_apply_common_imports`` already applied), so the
            caller can merge it into the install-time imports dict
            without re-walking the tree.
        """
        return self._inner.compile_app_root_arena(
            component,
            import_window_libraries,
            window_imports,
            out_path,
        )

    def compile_document_root_arena(
        self,
        head_components: list,
        html_lang: str | None,
        html_custom_attrs: dict,
        out_path: str,
    ) -> None:
        """Write ``.web/app/_document.js`` from the user's head config.

        The Python wrapper composes the ``<html><head><body>`` shell
        because the user-supplied ``head_components`` are user code
        that can't move into Rust. Once the tree is built it flows
        through the Rust PyO3 entry in one round-trip: Rust freezes
        the tree, harvests imports / renders the JSX from the
        snapshot, and writes ``_document.js`` without any
        ``_get_all_*`` calls from Python.

        Args:
            head_components: user-supplied head components (e.g. the
                list ``app.head_components``).
            html_lang: ``lang`` attribute for the top-level ``<html>``;
                defaults to ``"en"`` when ``None``.
            html_custom_attrs: extra attributes spliced onto ``<html>``
                (e.g. ``{"suppressHydrationWarning": True}``).
            out_path: absolute filesystem path for the emitted module.
        """
        existing_meta_types: set[str] = set()
        for component in head_components or []:
            if isinstance(component, Meta):
                if component.char_set is not None:  # pyright: ignore[reportAttributeAccessIssue]
                    existing_meta_types.add("char_set")
                if (
                    (name := component.name) is not None  # pyright: ignore[reportAttributeAccessIssue]
                    and name.equals(Var.create("viewport"))
                ):
                    existing_meta_types.add("viewport")

        always_head = [
            ReactMeta.create(),
            Link.create(
                rel="stylesheet",
                type="text/css",
                href=Var(
                    "reflexGlobalStyles",
                    _var_data=VarData(
                        imports={
                            "$/styles/__reflex_global_styles.css?url": [
                                ImportVar(tag="reflexGlobalStyles", is_default=True)
                            ]
                        }
                    ),
                ),
            ),
            Links.create(),
        ]
        maybe_head = []
        if "char_set" not in existing_meta_types:
            maybe_head.append(Meta.create(char_set="utf-8"))
        if "viewport" not in existing_meta_types:
            maybe_head.append(
                Meta.create(
                    name="viewport", content="width=device-width, initial-scale=1"
                )
            )

        combined_head = [
            preload_color_theme(),
            *(head_components or []),
            *maybe_head,
            *always_head,
        ]
        document_root = Html.create(
            Head.create(*combined_head),
            Body.create(
                Var("children"),
                ScrollRestoration.create(),
                Scripts.create(),
            ),
            lang=html_lang or "en",
            custom_attrs=html_custom_attrs or {},
        )

        self._inner.compile_document_root_arena(document_root, out_path)

    def compile_context_module(
        self,
        is_dev_mode: bool,
        default_color_mode_js: str,
        state_name: str | None,
        state_keys: list[str],
        initial_state_json: str,
        client_storage_json: str,
        out_path: str,
    ) -> None:
        """Write ``.web/utils/context.js``.

        Ports :func:`reflex_base.compiler.templates.context_template`.
        Python pre-serializes the dict inputs (``initial_state``,
        ``client_storage``); Rust assembles the template and writes the
        module.

        Args:
            is_dev_mode: emitted as ``export const isDevMode = …``.
            default_color_mode_js: the JS expression assigned to
                ``defaultColorMode`` (a quoted string or a runtime lookup).
            state_name: full dotted name of the state root; ``None`` for
                the no-state fallback.
            state_keys: full dotted names of every state context.
            initial_state_json: pre-serialized initial-state dict
                (``json_dumps``).
            client_storage_json: pre-serialized client-storage config
                (``json.dumps``).
            out_path: absolute filesystem path.
        """
        self._inner.compile_context_module(
            is_dev_mode,
            default_color_mode_js,
            state_name,
            list(state_keys),
            initial_state_json,
            client_storage_json,
            out_path,
        )

    def compile_stateful_pages_marker(self, routes: list[str], out_path: str) -> None:
        """Write ``.web/backend/stateful_pages.json``.

        Mirrors :meth:`App._write_stateful_pages_marker`. Python decides
        which routes are stateful; Rust serializes the list as JSON and
        writes the file.

        Args:
            routes: stateful route strings (no leading slash).
            out_path: absolute filesystem path.
        """
        self._inner.compile_stateful_pages_marker(list(routes), out_path)

    def should_memoize_arena_for_component(self, component: object) -> bool:
        """PR3 parity helper: apply the Rust arena predicate to a
        single ``Component``. Freezes the component, runs
        ``should_memoize_arena`` on the snapshot root, returns the bool.

        Used by ``tests/units/compiler/test_arena_parity.py`` to
        compare against Python ``_should_memoize`` per node.

        Returns:
            Whether the component should be memoized.
        """
        return bool(self._inner.should_memoize_arena_for_component(component))

    def snapshot_stats(self, component: object) -> dict[str, int]:
        """PR7 verification helper: freeze ``component`` and return a
        small stats dict (``node_count``, ``var_data_len``,
        ``vars_used_total``, ``unique_var_ids``) describing the
        snapshot. The dedup tests assert
        ``var_data_len == unique_var_ids`` once PR7 lands.

        Returns:
            Snapshot stats keyed by stat name.
        """
        return dict(self._inner.snapshot_stats(component))

    def dump_snapshot(self, component: object) -> dict:
        """Freeze ``component`` and return its IR as primitive Python data.

        Every field downstream code (memoize pass, JSX emitter) reads
        during compile is present in the returned dict. Tests rely on
        this to verify the snapshot carries enough information that
        Rust would not need any further PyO3 callback into Python
        during emit.

        Returns:
            A nested dict of primitives (str, int, list, tuple, dict).
            ``None`` is used in place of ``Symbol::EMPTY`` so callers
            can tell "field not set" apart from "field is empty
            string".
        """
        return self._inner.dump_snapshot(component)

    def should_memoize(self, component: object) -> bool:
        """Run the Rust memoize-decision walk on a Reflex ``Component``.

        Mirrors :func:`reflex.compiler.plugins.memoize._should_memoize`
        — plan §0a phase 2 / §0b lever (b2). Behavior-identical with
        the legacy predicate (parity-tested in
        ``tests/units/compiler/test_memoize_plugin.py``).

        Args:
            component: a ``reflex_base.components.component.BaseComponent``.

        Returns:
            ``True`` iff the component is a memoization candidate.
        """
        return bool(self._inner.should_memoize(component))

    def collect_all_imports(self, component: object) -> dict[str, list]:
        """Rust-merged equivalent of ``Component._get_all_imports()``.

        Walks the Component tree (children + ``_get_components_in_props``),
        calls each node's cached ``_get_imports()``, and merges in a Rust
        ``HashMap`` — drop-in replacement for the Python recursion that
        dominates ``rust_pipeline.compile_pages`` time on import-heavy
        trees.

        The return shape matches ``_get_all_imports`` exactly:
        ``dict[str, list[ImportVar]]`` with no ``$/utils/...`` prefix
        transform. Callers wrap in
        :func:`reflex.compiler.utils.merge_imports` for that step.

        Args:
            component: any ``reflex_base.components.component.BaseComponent``.

        Returns:
            The merged ``ParsedImportDict``.
        """
        return self._inner.collect_all_imports(component)

    def collect_all_imports_into(
        self, target: dict[str, list], component: object
    ) -> None:
        """In-place variant of :meth:`collect_all_imports`.

        Walks ``component``'s tree and appends every entry into
        ``target`` with the ``merge_imports`` ``$/utils/...`` prefix
        transform applied. Use this when accumulating across many
        Components (the ``compile_pages`` page + memo-body loop) so the
        caller doesn't pay the O(N²) cost of rebuilding the outer dict
        on each iteration via Python ``merge_imports``.

        Args:
            target: existing ``ParsedImportDict`` to merge into.
            component: any ``reflex_base.components.component.BaseComponent``.
        """
        self._inner.collect_all_imports_into(target, component)

    def last_phase_timings_ns(self) -> dict[str, int]:
        """Snapshot the Rust per-phase timings from the most recent compile.

        Counters reset at the start of every ``read_page``. Returns
        nanosecond totals keyed by phase name; see the Rust-side doc on
        ``CompilerSession.last_phase_timings_ns`` for the exact phases.

        Returns:
            ``dict[phase_name, ns_total]`` snapshot.
        """
        return self._inner.last_phase_timings_ns()

    def merge_imports_into(
        self, target: dict[str, list], source: dict[str, list]
    ) -> None:
        """Apply the ``merge_imports`` prefix transform to ``source`` in place.

        Same library-prefix rewrite as
        :func:`reflex.compiler.utils.merge_imports` but with no per-entry
        ``isinstance`` dispatch — callers must pass a pre-normalized
        ``ParsedImportDict`` (e.g. from ``parse_imports`` or
        ``_get_all_imports``).

        Args:
            target: existing ``ParsedImportDict`` to merge into.
            source: ``ParsedImportDict`` whose entries get appended.
        """
        self._inner.merge_imports_into(target, source)

    def compile_page_from_component_arena(
        self,
        component: object,
        route_ident: str,
        route: str,
        *,
        title: str | None = None,
        meta_tags: list[tuple[str, str]] | None = None,
        custom_code: list[str] | None = None,
        hooks_body: str | None = None,
    ) -> tuple[str, list[tuple[str, str]], dict[str, list]]:
        """PR4: arena-path page compile (planx.md cutover).

        Drives the full Component → JSX pipeline in one PyO3 call:

        1. ``freeze_component`` walks the Component tree into a
           ``Snapshot`` arena (single PyO3 walk).
        2. ``memoize_arena_pass`` inserts wrapper redirects + registers
           memo bodies (pure Rust, GIL released).
        3. ``emit_page_module_from_snapshot`` emits the page JSX.
        4. ``emit_memo_module_from_snapshot`` emits each unique memo
           body.
        5. ``pyread::collect_all_imports`` harvests the page-level
           import dict for the ``bun install`` step.

        Replaces the legacy ``walk_and_memoize`` (Python) +
        ``page_to_ir`` (Python msgpack) + ``compile_page_from_bytes``
        (Rust parse) chain — three crossings collapse to one.

        Args:
            component: the page's root ``BaseComponent`` instance.
            route_ident: JS identifier exported as ``__reflex_route_ident``.
            route: URL path emitted as ``__reflex_route``.
            title: optional document title.
            meta_tags: optional ``[(name_or_property, content), …]``.
            custom_code: caller-supplied custom-code blocks spliced
                between imports and the function shell. Per-node
                ``_get_all_custom_code()`` blocks are harvested from
                the snapshot automatically — pass extras here only for
                hand-rolled headers.
            hooks_body: caller-supplied hooks string spliced between
                the state-context lines and ``return``. Per-node
                ``hooks_internal``/``hooks_user`` are harvested from
                the snapshot automatically.

        Returns:
            ``(page_js, memo_bodies, imports)``:

            * ``page_js`` — full page module source.
            * ``memo_bodies`` — list of ``(name, jsx_source)`` for each
              unique memo body (already deduped by subtree_hash).
            * ``imports`` — page-level harvested import dict matching
              ``Component._get_all_imports()`` shape.
        """
        meta = list(meta_tags) if meta_tags else None
        page_js, bodies, imports_dict = self._inner.compile_page_from_component_arena(
            component,
            route_ident,
            route,
            title,
            meta,
            list(custom_code) if custom_code else None,
            hooks_body,
        )
        return str(page_js), [(str(n), str(j)) for n, j in bodies], imports_dict

    def write_if_changed(self, out_path: str, content: str) -> bool:
        """PR0 skip-if-unchanged write.

        Writes ``content`` to ``out_path`` only when the existing
        file's bytes differ. Returns ``True`` if the file was actually
        written, ``False`` when the existing contents already matched.
        Use this in place of ``pathlib.Path.write_text`` for compile
        outputs that may be regenerated unchanged — Vite HMR and
        file-watcher hooks key off mtime, so a no-op write still
        triggers a downstream reload.

        Args:
            out_path: absolute filesystem path.
            content: file body.

        Returns:
            ``True`` if the file was written, ``False`` if skipped.
        """
        return bool(self._inner.write_if_changed(out_path, content))
