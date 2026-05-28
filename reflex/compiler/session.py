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
        try:
            from reflex_compiler_rust import _native
        except ImportError as exc:
            raise RuntimeError(_WHEEL_MISSING) from exc
        self._inner = _native.CompilerSession()

    # ---- Cache controls -----------------------------------------------------

    def set_cache_capacity(self, cap: int | None) -> None:
        """Bound the in-process page-render cache. ``None`` for unbounded."""
        self._inner.set_cache_capacity(cap)

    def clear_cache(self) -> None:
        self._inner.clear_cache()

    def cache_len(self) -> int:
        return int(self._inner.cache_len())

    # ---- Compile entry points ----------------------------------------------

    def compile_memo_index(
        self, reexports: list[tuple[str, str]], out_path: str
    ) -> None:
        """Write the memo index module (``.web/utils/components.jsx``).

        Mirrors :func:`reflex_base.compiler.templates.memo_index_template`
        — the small barrel file that re-exports each ``@rx.memo`` custom
        component so ``root.jsx`` can pull them in via
        ``$/utils/components``. The Rust side builds the content and
        writes it to ``out_path`` in one PyO3 call.

        Args:
            reexports: list of ``(export_name, relative_module_specifier)``
                tuples; e.g. ``("Foo", "components/Foo")`` produces
                ``export { Foo } from "components/Foo";``.
            out_path: absolute filesystem path the index gets written
                to. Parent directory must already exist.
        """
        self._inner.compile_memo_index(list(reexports), out_path)

    def compile_styles_root(self, stylesheets: list[str], out_path: str) -> None:
        """Write ``.web/styles/styles.css``.

        Ports :func:`reflex_base.compiler.templates.styles_template`.

        Args:
            stylesheets: stylesheet URLs spliced into ``@import url(...)``
                lines under the single ``@layer __reflex_base;`` header.
            out_path: absolute filesystem path.
        """
        self._inner.compile_styles_root(list(stylesheets), out_path)

    def compile_theme_module(self, theme_js: str, out_path: str) -> None:
        """Write ``.web/utils/theme.js``.

        Ports :func:`reflex_base.compiler.templates.theme_template`. The
        ``theme_js`` argument is the JS object literal Python derives
        from the theme dict via ``LiteralVar.create(theme)``.

        Args:
            theme_js: the JS expression that becomes the default export.
            out_path: absolute filesystem path.
        """
        self._inner.compile_theme_module(theme_js, out_path)

    def compile_app_root_module(
        self,
        imports_str: str,
        dynamic_imports_str: str,
        custom_code_str: str,
        hooks_str: str,
        render_str: str,
        import_window_libraries: str,
        window_imports_str: str,
        out_path: str,
    ) -> None:
        """Write ``.web/app/root.jsx``.

        Ports :func:`reflex_base.compiler.templates.app_root_template`.
        Python pre-renders the dynamic strings (the legacy JSX renderer
        + hooks renderer); Rust splices them into the static layout.

        Args:
            imports_str: rendered ``import …`` lines joined with ``\\n``.
            dynamic_imports_str: rendered dynamic-import statements
                joined with ``\\n``.
            custom_code_str: user-contributed top-level code.
            hooks_str: rendered hook body.
            render_str: rendered JSX expression for the app-wrap chain.
            import_window_libraries: rendered
                ``import * as <alias> from "…"`` lines.
            window_imports_str: rendered ``"<path>": <alias>,`` entries.
            out_path: absolute filesystem path.
        """
        self._inner.compile_app_root_module(
            imports_str,
            dynamic_imports_str,
            custom_code_str,
            hooks_str,
            render_str,
            import_window_libraries,
            window_imports_str,
            out_path,
        )

    def compile_document_root_module(
        self,
        imports_str: str,
        document_render_str: str,
        out_path: str,
    ) -> None:
        """Write ``.web/app/_document.js``.

        Ports :func:`reflex_base.compiler.templates.document_root_template`.

        Args:
            imports_str: rendered ``import …`` lines joined with ``\\n``.
            document_render_str: rendered JSX expression for the
                document tree.
            out_path: absolute filesystem path.
        """
        self._inner.compile_document_root_module(
            imports_str, document_render_str, out_path
        )

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
        """
        return bool(self._inner.should_memoize_arena_for_component(component))

    def snapshot_stats(self, component: object) -> dict[str, int]:
        """PR7 verification helper: freeze ``component`` and return a
        small stats dict (``node_count``, ``var_data_len``,
        ``vars_used_total``, ``unique_var_ids``) describing the
        snapshot. The dedup tests assert
        ``var_data_len == unique_var_ids`` once PR7 lands.
        """
        return dict(self._inner.snapshot_stats(component))

    def dump_snapshot(self, component: object) -> dict:
        """Freeze ``component`` and return its ``Snapshot`` as a plain dict.

        This is the parity-oracle vehicle for the Python-freezer work: the
        dump is a lossless, deterministic serialization of every
        emit-relevant snapshot field (``id()`` values are omitted). Two
        snapshots compare equal iff their dumps do, so the eventual
        gather-path snapshot can be proven byte-identical to the Rust
        freeze walk via ``dump_snapshot`` on both. The snapshot is dumped
        before the memoize pass, so it reflects the pure frozen tree.

        Args:
            component: the root ``BaseComponent`` instance to freeze.

        Returns:
            A nested dict mirroring the ``Snapshot`` arena: ``root``,
            ``nodes`` (per-node fields), the ``var_data`` table + dense
            backings, ``control_flow`` side tables, ``rename_props``,
            ``special_props``, ``app_style_map``, ``app_wraps``, and
            ``page_meta``.
        """
        return dict(self._inner.dump_snapshot(component))

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

    def compile_page_from_arena(
        self,
        bundle: dict,
        route_ident: str,
        route: str,
        *,
        title: str | None = None,
        meta_tags: list[tuple[str, str]] | None = None,
        custom_code: list[str] | None = None,
        hooks_body: str | None = None,
        compute_close: bool = False,
    ) -> tuple[str, list[tuple[str, str]]]:
        """Compile a page from a pre-gathered snapshot wire bundle (PR A).

        The Rust side rebuilds the ``Snapshot`` from ``bundle`` (the
        inverse of :meth:`dump_snapshot`), then runs the same memoize +
        emit tail as :meth:`compile_page_from_component_arena`. For a
        bundle equal to ``dump_snapshot(component)`` the returned page JSX
        and memo bodies are byte-identical to the freeze path.

        Unlike the freeze entrypoint this returns no page-level imports
        dict — the bundle carries per-node imports inside the snapshot;
        the ``bun install`` dict is gathered separately on the Python side
        alongside the bundle.

        Args:
            bundle: a snapshot wire dict as produced by
                :meth:`dump_snapshot` (or the future Python gatherer).
            route_ident: JS identifier exported as ``__reflex_route_ident``.
            route: URL path emitted as ``__reflex_route``.
            title: optional document title.
            meta_tags: optional ``[(name_or_property, content), …]``.
            custom_code: caller-supplied custom-code blocks.
            hooks_body: caller-supplied hooks string.
            compute_close: recompute ``subtree_hash`` / ``PROPAGATES_HOOKS``
                Rust-side. Pass ``False`` for a :meth:`dump_snapshot` bundle
                (those fields are present); ``True`` for a native gatherer
                bundle that omits them.

        Returns:
            ``(page_js, memo_bodies)`` where ``memo_bodies`` is a list of
            ``(name, jsx_source)`` for each unique memo body.
        """
        meta = list(meta_tags) if meta_tags else None
        page_js, bodies = self._inner.compile_page_from_arena(
            bundle,
            route_ident,
            route,
            title,
            meta,
            list(custom_code) if custom_code else None,
            hooks_body,
            compute_close,
        )
        return str(page_js), [(str(n), str(j)) for n, j in bodies]

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
