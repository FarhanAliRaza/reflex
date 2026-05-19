"""Python wrapper around the Rust ``CompilerSession``.

The supported compile path is two-phase:

* Phase 1 — Python: :func:`reflex.compiler.ir.bridge.page_to_ir` walks
  a finalized Component tree and emits msgpack-packed IR bytes.
* Phase 2 — Rust: :meth:`CompilerSession.compile_page_from_bytes` (and
  the memo equivalent) parses the bytes and emits JSX with no callbacks
  into Python.

The thin wrapper around ``_native.CompilerSession`` here mostly forwards
calls. The remaining PyO3 callbacks (``should_memoize``,
``collect_all_imports*``, ``merge_imports_into``) run in phase 1 — before
the bridge produces bytes — so phase 2 is callback-free.
"""

from __future__ import annotations

_WHEEL_MISSING = (
    "reflex_compiler_rust wheel not available — install it via "
    "`maturin develop --release` in packages/reflex-compiler-rust."
)


class CompilerSession:
    """Long-lived compiler handle. Shared across hot-reloads.

    Constructing this is cheap (no compile work happens). The Rust side
    owns the per-process state (timing cells, memo-body collector).
    """

    def __init__(self) -> None:
        try:
            from reflex_compiler_rust import _native
        except ImportError as exc:
            raise RuntimeError(_WHEEL_MISSING) from exc
        self._inner = _native.CompilerSession()
        # Cache for the app-root imports walk. The wrapper composition
        # (StrictMode/Theme/ToasterProvider/user wraps) is class-level and
        # stable across hot-reloads in a long-running session, so walking
        # the app_root tree once per process is enough. Keyed on the
        # identity-stable tuple computed by ``_app_root_cache_key``; value
        # is the raw (un-prefixed) imports dict from
        # ``collect_all_imports``. Merge via ``merge_imports_into`` to
        # apply the ``$/utils/...`` prefix transform on hit.
        self._app_root_imports_cache: (
            tuple[tuple[tuple, ...], dict[str, list]] | None
        ) = None
        self._app_root_imports_walks: int = 0

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

    def collect_app_root_imports_cached(
        self,
        target: dict[str, list],
        app_root: object,
        cache_key: tuple[tuple, ...],
    ) -> dict[str, list]:
        """Walk ``app_root`` for imports, caching across compiles.

        The app-root wrapper composition (StrictMode/Theme/Toaster/user
        wraps) is class-level and stable for the lifetime of the Python
        process, so the import-walk result can be cached on the session.
        On cache hit, this is equivalent to
        :meth:`merge_imports_into`-ing the cached raw imports into
        ``target``. On miss, performs a fresh walk via
        :meth:`collect_all_imports` and stores the result.

        The cache stores the **raw** (un-prefixed) import dict — the same
        shape ``collect_all_imports`` returns — so that
        :meth:`merge_imports_into` applies the ``$/utils/...`` prefix
        transform exactly once per merge. The raw dict is returned so
        callers that need the un-prefixed form (e.g. the app-root JSX
        emit's ``imports_str`` build) can skip a second
        ``app_root._get_all_imports()`` walk.

        Args:
            target: existing ``ParsedImportDict`` to merge into.
            app_root: the composed app-root ``Component`` tree.
            cache_key: an identity-stable key derived from the wrapper
                composition. Cache invalidates when this changes.

        Returns:
            The raw (un-prefixed) app-root import dict — same shape as
            ``Component._get_all_imports()``. Callers should treat it as
            read-only; mutate via a shallow copy if needed.
        """
        cached = self._app_root_imports_cache
        if cached is not None and cached[0] == cache_key:
            self.merge_imports_into(target, cached[1])
            return cached[1]
        raw = self.collect_all_imports(app_root)
        raw_dict = dict(raw)
        self._app_root_imports_cache = (cache_key, raw_dict)
        self._app_root_imports_walks += 1
        self.merge_imports_into(target, raw_dict)
        return raw_dict

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

    def compile_memo_from_bytes(
        self,
        name: str,
        signature: str,
        ir_bytes: bytes,
        *,
        pre_hooks: str = "",
    ) -> str:
        """Phase-2 memo entry point: compile a memo module from IR bytes.

        Memo equivalent of :meth:`compile_page_from_bytes`. The
        memo body Component must already carry the ``{children}`` hole
        substitution (passthrough wrappers) before being serialized via
        :func:`reflex.compiler.ir.bridge.page_to_ir`.

        Args:
            name: exported memo identifier.
            signature: parameter list spliced after ``memo(`` (e.g.
                ``"({ children })"`` for passthroughs, ``"()"`` for
                snapshot bodies).
            ir_bytes: msgpack-packed IR for the memo body.
            pre_hooks: optional pre-rendered hook block.

        Returns:
            Rendered JS source for the memo module.
        """
        return str(
            self._inner.compile_memo_from_bytes(
                name, signature, ir_bytes, pre_hooks
            )
        )

    def compile_page_from_bytes(
        self,
        route_ident: str,
        ir_bytes: bytes,
        *,
        custom_code: list[str] | None = None,
        hooks_body: str | None = None,
    ) -> str:
        """Phase-2 entry point: compile a page from already-serialized IR.

        Pure two-phase model — Python produced ``ir_bytes`` via
        :func:`reflex.compiler.ir.bridge.page_to_ir`; this method parses
        the msgpack, runs the emitter, and returns the JSX source. **No
        PyO3 callbacks during emit**: route, title, meta, component
        imports, state bindings, and ``needs_ref`` are all read from the
        IR itself. The GIL is released for the parse + emit span.

        Args:
            route_ident: JS identifier used for the route export.
            ir_bytes: msgpack-packed Page IR (schema v2).
            custom_code: optional pre-rendered custom-code blocks.
            hooks_body: optional pre-rendered hooks-body string.

        Returns:
            Rendered JS source for the page module.
        """
        return str(
            self._inner.compile_page_from_bytes(
                route_ident,
                ir_bytes,
                list(custom_code) if custom_code else None,
                hooks_body,
            )
        )

