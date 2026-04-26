"""Templates and emitters for the Astro frontend target.

The Astro target generates one Astro page per Reflex route under
``.web/src/pages/``. Public surface here is intentionally pure: every function
returns an artifact path / string pair, so the existing post-compile pipeline
can write the files without any Astro-specific runtime dependency.

See ``ASTRO_MIGRATION_TASKS.md`` Master Tasks 1-3 and 6 for the design notes
this module implements.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Iterable, Sequence
from typing import Literal

from reflex_base.utils.exceptions import CompileError

RenderMode = Literal["static", "app", "islands"]
HydrateDirective = Literal[
    "client:load", "client:idle", "client:visible", "client:only"
]

# Reflex route arg patterns (mirror reflex_base.constants.route.RouteRegex).
_OPTIONAL_CATCHALL_RE = re.compile(r"\[\[\.\.\.([a-zA-Z_]\w*)\]\]")
_STRICT_CATCHALL_RE = re.compile(r"\[\.\.\.([a-zA-Z_]\w*)\]")
_OPTIONAL_ARG_RE = re.compile(r"\[\[([a-zA-Z_]\w*)\]\]")
_ARG_RE = re.compile(r"\[([a-zA-Z_]\w*)\]")


def astro_route_to_file_path(route: str) -> str:
    """Translate a Reflex route string into an Astro page file path.

    Reflex uses ``[arg]`` for required dynamic, ``[[arg]]`` for optional,
    ``[...rest]`` for catchall, and ``[[...rest]]`` for optional catchall.
    Astro supports ``[arg]`` and ``[...rest]`` directly. Optional variants
    collapse to the required form for the file path; the optional behavior
    is implemented inside ``getStaticPaths()`` (a path of "" is included).

    The returned path is the layout under ``.web/`` — i.e.
    ``"src/pages/<route>.astro"`` — so callers can resolve it directly
    against the web dir. The ``"src/"`` prefix matches Astro's project
    layout convention.

    Args:
        route: The Reflex route. Must start with ``"/"``.

    Returns:
        The relative file path under ``.web/``. The empty / "/" route maps
        to ``"src/pages/index.astro"``.

    Raises:
        CompileError: If ``route`` does not start with "/".
    """
    if not route or not route.startswith("/"):
        msg = f"Astro route must start with '/'; got {route!r}."
        raise CompileError(msg)
    stripped = route.strip("/")
    if not stripped:
        return "src/pages/index.astro"

    # Collapse optional catchalls/args: [[...x]] -> [...x], [[x]] -> [x]
    normalized = _OPTIONAL_CATCHALL_RE.sub(r"[...\1]", stripped)
    normalized = _OPTIONAL_ARG_RE.sub(r"[\1]", normalized)
    return f"src/pages/{normalized}.astro"


def astro_island_module_path(route: str, name: str) -> str:
    """Compute the relative path to a per-page island module.

    Args:
        route: The Reflex route the island lives under (used for namespacing).
        name: The PascalCase name of the island component.

    Returns:
        Relative path under ``.web/`` (i.e. ``"src/reflex/islands/.../<name>.tsx"``).
    """
    if not route.startswith("/"):
        msg = f"Astro route must start with '/'; got {route!r}."
        raise CompileError(msg)
    stripped = route.strip("/") or "index"
    safe_dir = re.sub(r"[\[\]]", "", stripped) or "index"
    return f"src/reflex/islands/{safe_dir}/{name}.tsx"


@dataclasses.dataclass(frozen=True)
class AstroIsland:
    """Compiler-resolved description of one client island on an Astro page.

    Attributes:
        component_name: The PascalCase identifier for the island's React
            module export (used as the JSX tag in the generated ``.astro``).
        module_path: The Astro-relative import path for the React module,
            e.g. ``"../reflex/islands/blog/Sidebar.tsx"``.
        directive: The Astro ``client:*`` directive to emit. ``"client:only"``
            forces the runtime to skip prerender and only mount the component
            in the browser.
        media: Optional CSS media query to attach to the directive (only
            valid alongside ``"client:visible"`` / ``"client:idle"`` / etc.).
    """

    component_name: str
    module_path: str
    directive: HydrateDirective
    media: str | None = None


def _format_island_tag(island: AstroIsland) -> str:
    """Render a single ``<Component client:* />`` element.

    Args:
        island: The island descriptor.

    Returns:
        A self-closing JSX tag string.
    """
    if island.directive == "client:only":
        # client:only takes a framework name, not a media query.
        return f'  <{island.component_name} client:only="react" />'
    if island.media is not None:
        media_attr = json.dumps(island.media)
        return f"  <{island.component_name} {island.directive}={{{media_attr}}} />"
    return f"  <{island.component_name} {island.directive} />"


def astro_page_template(
    *,
    render_mode: RenderMode,
    title: str,
    layout_import: str = "../layouts/Layout.astro",
    page_root_import: str | None = None,
    page_root_name: str = "PageRoot",
    static_html: str = "",
    islands: Sequence[AstroIsland] = (),
    static_paths: Sequence[dict[str, str]] | None = None,
) -> str:
    """Render one Astro page file (``.astro`` source) for a Reflex route.

    Args:
        render_mode: One of ``"static"``, ``"app"``, ``"islands"``.
        title: The page title injected into the layout.
        layout_import: Astro-relative import path for the shared layout.
        page_root_import: For ``"app"`` mode, the Astro-relative import path
            for the page-root React module. Required for ``"app"``, ignored
            otherwise.
        page_root_name: Identifier used for the page-root import.
        static_html: Pre-rendered HTML for static / islands modes.
        islands: For ``"islands"`` mode, the list of compiler-placed islands
            to emit. Each becomes a JSX element under the layout slot.
        static_paths: For dynamic routes (``[arg]`` / ``[...arg]``), the
            compile-time list of params dicts. When provided, the rendered
            page wraps a ``getStaticPaths()`` export.

    Returns:
        The full ``.astro`` source.

    Raises:
        CompileError: If required inputs for the chosen render_mode are
            missing (e.g. ``"app"`` without ``page_root_import``).
    """
    if render_mode not in ("static", "app", "islands"):
        msg = (
            f"Invalid render_mode={render_mode!r}. "
            f"Expected 'static', 'app', or 'islands'."
        )
        raise CompileError(msg)
    if render_mode == "app" and not page_root_import:
        msg = "render_mode='app' requires page_root_import to be set."
        raise CompileError(msg)
    if render_mode == "static" and (page_root_import or islands):
        msg = (
            "render_mode='static' must not include page_root_import or "
            "islands. State and event usage is rejected at compile time."
        )
        raise CompileError(msg)

    title_literal = json.dumps(title)
    frontmatter_imports: list[str] = [
        f"import Layout from {json.dumps(layout_import)};",
    ]

    body_lines: list[str] = []

    if render_mode == "app":
        assert page_root_import is not None  # narrowed by the check above
        frontmatter_imports.append(
            f"import {page_root_name} from {json.dumps(page_root_import)};"
        )
        body_lines.append(f"  <{page_root_name} client:load />")
    elif render_mode == "islands":
        seen: set[tuple[str, str]] = set()
        for isl in islands:
            key = (isl.component_name, isl.module_path)
            if key in seen:
                continue
            seen.add(key)
            frontmatter_imports.append(
                f"import {{ {isl.component_name} }} from {json.dumps(isl.module_path)};"
            )
        if static_html:
            body_lines.extend("  " + line for line in static_html.splitlines())
        body_lines.extend(_format_island_tag(isl) for isl in islands)
    elif static_html:
        # static
        body_lines.extend("  " + line for line in static_html.splitlines())

    static_paths_block = ""
    if static_paths is not None:
        # Emit `export async function getStaticPaths() { return [...]; }`.
        rendered = json.dumps(
            [{"params": p} for p in static_paths],
            indent=2,
        )
        static_paths_block = (
            f"export async function getStaticPaths() {{\n  return {rendered};\n}}\n"
        )

    frontmatter = "\n".join([
        *frontmatter_imports,
        "",
        f"const title = {title_literal};",
        *(["", static_paths_block.rstrip()] if static_paths_block else []),
    ]).rstrip()

    body = "\n".join(body_lines).rstrip()
    if not body:
        body = "  <!-- empty page -->"

    layout_open = "<Layout title={title}>"  # Astro JSX, not a Python f-string.  # noqa: RUF027
    return f"---\n{frontmatter}\n---\n{layout_open}\n{body}\n</Layout>\n"


def astro_color_mode_inline_script(
    *,
    cookie_name: str = "reflex-color-mode",
    storage_key: str = "color_mode",
    default_color_mode: Literal["light", "dark", "system"] = "system",
) -> str:
    """Render the inline head script that prevents flash-of-wrong-theme.

    Runs synchronously before first paint, reads the persisted color mode
    in this fallback order: cookie -> localStorage -> system preference ->
    ``default_color_mode``, and applies the resolved value to ``<html>`` as
    both a class (``light``/``dark``) and a ``data-color-mode`` attribute.

    The script intentionally does not import the Reflex runtime; it only
    needs to run on every page including ``render_mode="static"`` pages
    that ship 0 KiB of first-party JS.

    Args:
        cookie_name: Cookie name used by the Reflex color-mode persistence.
        storage_key: localStorage key used by the Reflex color-mode persistence.
        default_color_mode: Fallback when neither cookie, storage, nor the
            system preference is conclusive. ``"system"`` resolves to
            ``prefers-color-scheme: dark`` at runtime.

    Returns:
        The ``<script>`` body as an HTML-injectable string (no surrounding
        ``<script>`` tags so callers can decide attributes like ``is:inline``).
    """
    cookie = json.dumps(cookie_name)
    storage = json.dumps(storage_key)
    default_mode = json.dumps(default_color_mode)
    return (
        "(function () {\n"
        "  try {\n"
        "    var resolved = null;\n"
        f"    var match = document.cookie.match(new RegExp('(^|;\\\\s*)' + {cookie} + '=([^;]+)'));\n"
        "    if (match) { resolved = decodeURIComponent(match[2]); }\n"
        "    if (!resolved) {\n"
        "      try {\n"
        f"        var stored = window.localStorage.getItem({storage});\n"
        "        if (stored) { resolved = stored; }\n"
        "      } catch (e) { /* private mode / disabled storage */ }\n"
        "    }\n"
        "    if (!resolved || resolved === 'system') {\n"
        f"      var fallback = {default_mode};\n"
        "      if (fallback === 'system') {\n"
        "        resolved = window.matchMedia('(prefers-color-scheme: dark)').matches\n"
        "          ? 'dark'\n"
        "          : 'light';\n"
        "      } else {\n"
        "        resolved = fallback;\n"
        "      }\n"
        "    }\n"
        "    var root = document.documentElement;\n"
        "    if (resolved === 'dark') {\n"
        "      root.classList.add('dark');\n"
        "      root.classList.remove('light');\n"
        "    } else {\n"
        "      root.classList.add('light');\n"
        "      root.classList.remove('dark');\n"
        "    }\n"
        "    root.setAttribute('data-color-mode', resolved);\n"
        "  } catch (e) { /* defensive: never block first paint */ }\n"
        "})();"
    )


def astro_layout_template(
    *,
    base_path: str = "",
    color_mode_script: str | None = None,
) -> str:
    """Render the baseline ``Layout.astro`` shared by every Astro page.

    Args:
        base_path: The configured ``frontend_path``. Currently informational —
            Astro derives the public base path from ``astro.config.mjs``.
        color_mode_script: When provided, an inline ``<script is:inline>``
            block is injected into ``<head>`` to set the color mode before
            first paint. Pass the result of :func:`astro_color_mode_inline_script`.

    Returns:
        The full ``Layout.astro`` source.
    """
    # base_path is intentionally unused for now; kept on the signature so
    # the layout can later inject a <base href> tag once frontend_path is
    # threaded through the build.
    _ = base_path
    color_mode_block = (
        f"    <script is:inline>{color_mode_script}</script>\n"
        if color_mode_script
        else ""
    )
    return (
        "---\n"
        "const { title } = Astro.props;\n"
        "---\n"
        "<!doctype html>\n"
        '<html lang="en">\n'
        "  <head>\n"
        '    <meta charset="UTF-8" />\n'
        '    <meta name="viewport" content="width=device-width, initial-scale=1" />\n'
        "    <title>{title}</title>\n"
        f"{color_mode_block}"
        "  </head>\n"
        "  <body>\n"
        "    <slot />\n"
        "  </body>\n"
        "</html>\n"
    )


def astro_config_template(
    *,
    site: str | None = None,
    base: str = "",
    host: str = "0.0.0.0",
    port: int | None = None,
    public_assets: str = "public",
) -> str:
    """Render an ``astro.config.mjs`` for the Astro frontend target.

    The output is intentionally static-only (``output: "static"``) and uses
    the ``@astrojs/react`` integration. No SSR adapter is configured.

    Args:
        site: Optional canonical site URL used by Astro for absolute links.
        base: Optional base path matching ``frontend_path`` from rx.Config.
        host: Dev server host. Defaults to ``"0.0.0.0"`` to match the React
            Router target's ``--host`` flag.
        port: Dev server port. ``None`` lets Astro pick its default (4321).
        public_assets: Directory under ``.web`` to serve at ``"/"`` during
            dev. Defaults to ``"public"`` to mirror Reflex's existing layout.

    Returns:
        The full ``astro.config.mjs`` source.
    """
    site_line = f"  site: {json.dumps(site)},\n" if site else ""
    base_line = f"  base: {json.dumps(base)},\n" if base else ""
    server_lines: list[str] = [f"    host: {json.dumps(host)},"]
    if port is not None:
        server_lines.append(f"    port: {int(port)},")
    server_block = "\n".join(server_lines)

    return (
        '// Generated by Reflex (frontend_target="astro"). Do not edit.\n'
        'import { defineConfig } from "astro/config";\n'
        'import react from "@astrojs/react";\n'
        "\n"
        "export default defineConfig({\n"
        '  output: "static",\n'
        f"{site_line}"
        f"{base_line}"
        "  integrations: [react()],\n"
        f"  publicDir: {json.dumps(public_assets)},\n"
        "  server: {\n"
        f"{server_block}\n"
        "  },\n"
        "  vite: {\n"
        "    resolve: {\n"
        '      alias: { "$": "/src", "@": "/src" },\n'
        "    },\n"
        "  },\n"
        "});\n"
    )


def astro_page_root_island_template(
    *,
    page_module_import: str,
    page_module_default_export: bool = True,
) -> str:
    """Render the per-page React module that an ``app``-mode .astro file mounts.

    The returned module re-exports the existing Reflex page component as
    ``default`` so the .astro file's ``<PageRoot client:load />`` directive
    finds it. Once the Phase A Zustand runtime lands, this module will also
    bootstrap the runtime (Zustand store, event loop, socket).

    Args:
        page_module_import: The path to the page's existing Reflex-generated
            React module, relative to the island module's location.
        page_module_default_export: Whether the page module exposes the
            component as default (``true``) or named ``Component`` (``false``).

    Returns:
        The ``.tsx`` source of the page-root island module.
    """
    if page_module_default_export:
        import_line = f"import Page from {json.dumps(page_module_import)};"
    else:
        import_line = (
            f"import {{ Component as Page }} from {json.dumps(page_module_import)};"
        )

    return (
        '// Generated by Reflex (frontend_target="astro"). Do not edit.\n'
        f"{import_line}\n"
        "\n"
        "export default function PageRoot() {\n"
        "  return <Page />;\n"
        "}\n"
    )


@dataclasses.dataclass(frozen=True)
class AstroPageArtifact:
    """One generated file destined for the Astro target's ``.web`` tree.

    Attributes:
        path: Path relative to ``.web/src/`` (forward slashes only).
        contents: The full file contents as a string.
    """

    path: str
    contents: str


@dataclasses.dataclass(frozen=True)
class AstroEmitterInput:
    """Inputs to :func:`emit_astro_page`.

    Attributes:
        route: The Reflex route. Must start with "/".
        title: The page title (drives ``<title>`` and the layout prop).
        render_mode: One of ``"static"``, ``"app"``, ``"islands"``.
        page_module_import: Astro-relative path to the React page module
            (used for ``"app"`` mode). Required when ``render_mode="app"``.
        static_html: Pre-rendered HTML for static / islands modes.
        islands: Compiler-placed islands for ``"islands"`` mode.
        static_paths: Compile-time list of params dicts for dynamic routes.
    """

    route: str
    title: str
    render_mode: RenderMode = "app"
    page_module_import: str | None = None
    static_html: str = ""
    islands: tuple[AstroIsland, ...] = ()
    static_paths: tuple[dict[str, str], ...] | None = None


def emit_astro_page(spec: AstroEmitterInput) -> AstroPageArtifact:
    """Emit one Astro page artifact for a single Reflex route.

    This is the per-page entry point of the Astro target. The plugin layer
    calls it once per registered page; output paths are unique per route, so
    the writer can dump the artifacts straight into ``.web/src/`` without
    deduplication.

    Args:
        spec: The :class:`AstroEmitterInput` describing the page.

    Returns:
        The :class:`AstroPageArtifact` (path + contents) for this route.

    Raises:
        CompileError: If the spec is internally inconsistent (e.g. ``"app"``
            without a ``page_module_import``, or static_html on a static page
            attempting to mount islands).
    """
    file_path = astro_route_to_file_path(spec.route)
    contents = astro_page_template(
        render_mode=spec.render_mode,
        title=spec.title,
        page_root_import=spec.page_module_import,
        static_html=spec.static_html,
        islands=spec.islands,
        static_paths=list(spec.static_paths) if spec.static_paths else None,
    )
    return AstroPageArtifact(path=file_path, contents=contents)


def emit_astro_layout(
    *,
    base_path: str = "",
    inline_color_mode_script: bool = True,
    default_color_mode: Literal["light", "dark", "system"] = "system",
) -> AstroPageArtifact:
    """Emit the shared ``Layout.astro`` artifact.

    Args:
        base_path: Optional ``frontend_path`` for future <base> tag use.
        inline_color_mode_script: When True (default), the layout includes
            the inline head script that resolves the color mode before
            first paint. Disable only for tests that want a minimal layout.
        default_color_mode: Fallback color mode used when no cookie /
            localStorage value is set (and the system preference is
            inconclusive on platforms that do not support
            ``prefers-color-scheme``).

    Returns:
        The :class:`AstroPageArtifact` at ``src/layouts/Layout.astro``.
    """
    color_mode_script = (
        astro_color_mode_inline_script(default_color_mode=default_color_mode)
        if inline_color_mode_script
        else None
    )
    return AstroPageArtifact(
        path="src/layouts/Layout.astro",
        contents=astro_layout_template(
            base_path=base_path, color_mode_script=color_mode_script
        ),
    )


def emit_astro_config(
    *,
    site: str | None = None,
    base: str = "",
    host: str = "0.0.0.0",
    port: int | None = None,
) -> AstroPageArtifact:
    """Emit ``astro.config.mjs`` at the ``.web`` root.

    Args:
        site: Optional canonical site URL.
        base: Optional base path (corresponds to ``rx.Config.frontend_path``).
        host: Dev server host. Defaults to ``"0.0.0.0"``.
        port: Dev server port. ``None`` lets Astro pick its default.

    Returns:
        The :class:`AstroPageArtifact` at ``"astro.config.mjs"`` (relative
        to ``.web/`` — sibling of ``package.json``).
    """
    return AstroPageArtifact(
        path="astro.config.mjs",
        contents=astro_config_template(site=site, base=base, host=host, port=port),
    )


def emit_astro_page_root_island(
    *,
    route: str,
    page_module_import: str,
    page_module_default_export: bool = True,
) -> AstroPageArtifact:
    """Emit the per-page React module for an ``app``-mode page.

    Args:
        route: The Reflex route (used to compute the island file path).
        page_module_import: Astro-relative path back to the existing Reflex
            page module.
        page_module_default_export: Whether that module's component is
            exported as default (``true``) or named ``Component`` (``false``).

    Returns:
        The :class:`AstroPageArtifact` placed under
        ``reflex/islands/<route>/PageRoot.tsx``.
    """
    return AstroPageArtifact(
        path=astro_island_module_path(route, "PageRoot"),
        contents=astro_page_root_island_template(
            page_module_import=page_module_import,
            page_module_default_export=page_module_default_export,
        ),
    )


def emit_astro_artifacts(
    pages: Iterable[AstroEmitterInput],
    *,
    site: str | None = None,
    base: str = "",
    host: str = "0.0.0.0",
    port: int | None = None,
) -> list[AstroPageArtifact]:
    """Emit the full Astro artifact set for the build.

    The result is the per-page ``.astro`` files plus the shared layout and
    ``astro.config.mjs``. ``app``-mode pages also get a per-page
    ``PageRoot.tsx`` island module.

    Args:
        pages: One :class:`AstroEmitterInput` per Reflex route.
        site: Optional canonical site URL passed to ``astro.config.mjs``.
        base: Optional ``base`` path passed to ``astro.config.mjs``.
        host: Dev server host.
        port: Dev server port.

    Returns:
        The list of :class:`AstroPageArtifact` instances ready to write.
    """
    artifacts: list[AstroPageArtifact] = [
        emit_astro_layout(base_path=base),
        emit_astro_config(site=site, base=base, host=host, port=port),
    ]
    for spec in pages:
        artifacts.append(emit_astro_page(spec))
        if spec.render_mode == "app":
            assert spec.page_module_import is not None
            artifacts.append(
                emit_astro_page_root_island(
                    route=spec.route,
                    page_module_import=spec.page_module_import,
                )
            )
    return artifacts
