"""Static-HTML renderer for ``render_mode="islands"`` Astro pages.

For ``islands`` mode we emit ``.web/src/pages/<route>.astro`` with inline
Astro HTML for static subtrees and one ``<ComponentName client:*/>``
element per compiler-detected island.

This module turns a compiled Reflex render tree into:

- a string of Astro template content (HTML mixed with ``<IslandName client:*/>``
  references) suitable for inlining inside a ``.astro`` file's ``<Layout>`` slot,
- and one :class:`AstroPageArtifact` per island carrying a per-route React
  module that re-exports the underlying ``ExperimentalMemoComponent`` wrapper.

The renderer walks the compiled root component (``page_ctx.root_component``).
Auto-memoized stateful subtrees show up as
:class:`reflex.experimental.memo.ExperimentalMemoComponent` instances; each
becomes one island. Everything else renders as inline HTML.

The implementation is intentionally minimal: it does not attempt to handle
state-bound vars, ``rx.cond`` / ``rx.foreach`` / ``rx.match`` outside of an
island boundary (those are state-dependent and are guaranteed to live inside
an island after the auto-memo pass), or arbitrary props. Edge cases fall back
to a placeholder HTML comment so the build never fails silently.
"""

from __future__ import annotations

import dataclasses
import html
import re
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from reflex_base.compiler.astro import AstroPageArtifact, astro_island_module_path
from reflex_base.compiler.islands_classifier import classify_islands

if TYPE_CHECKING:
    from reflex_base.components.component import BaseComponent


@dataclasses.dataclass(frozen=True)
class IslandsRenderResult:
    """The output of :func:`render_islands_page`.

    Attributes:
        body: The HTML+Astro template string that goes between the
            ``<Layout>...</Layout>`` tags of the .astro file.
        imports: One Astro frontmatter import line per island module.
        island_modules: Per-route React modules to write under
            ``src/reflex/islands/<route>/<IslandName>.tsx``. Each module
            re-exports the corresponding ``ExperimentalMemoComponent``
            wrapper so Astro mounts it as a self-contained island.
        directives: Sequence of ``client:*`` directives used (one per
            island, in placement order).
    """

    body: str
    imports: tuple[str, ...]
    island_modules: tuple[AstroPageArtifact, ...]
    directives: tuple[str, ...]


def _strip_quotes(s: Any) -> str:
    """Best-effort: extract the inner string from a Reflex JSX name/contents.

    Reflex's render dict stores tag names as ``'"div"'`` (string literal) and
    component identifiers as ``"MyComponent"`` (bare). Contents come back as
    ``'"hello"'`` for literals or as raw JS expressions for state vars. This
    helper unwraps the literal form and returns the JS expression untouched.

    Args:
        s: The raw value from the render dict.

    Returns:
        The Python string with surrounding double-quotes removed when present.
    """
    text = str(s)
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return text


def _is_html_tag_name(name: str) -> bool:
    """Heuristic for detecting an HTML tag (lowercase) vs. a React identifier.

    Args:
        name: The unquoted tag name from the render dict.

    Returns:
        Whether the name looks like an HTML element name.
    """
    return bool(name) and name[0].islower() and "_" not in name and name != "Fragment"


def _looks_like_state_expression(text: str) -> bool:
    """Whether ``text`` is a JS expression referencing Reflex runtime state.

    These appear inside ``contents`` when the underlying value is a state
    var that survived to the static portion of the tree. Such cases should
    have been moved into an island by the auto-memo plugin, but we keep a
    defensive check so the renderer never silently emits an undefined JS
    identifier as raw HTML.

    Args:
        text: The contents string to inspect.

    Returns:
        True if ``text`` references a Reflex state path or runtime helper.
    """
    return bool(
        re.search(r"\b(reflex_+state_+|addEvents|ReflexEvent|_rx_state_\b)", text)
    )


def _render_props_as_attrs(props: Iterable[str]) -> str:
    """Render the props array from a Reflex render dict to HTML attributes.

    Reflex stores props as ``"name:value"`` strings where ``value`` is JS.
    This minimal renderer keeps obvious string literal attributes
    (``class``, ``id``, ``style``, ``data-*``, ``aria-*``) and drops props
    whose value cannot be expressed as a static HTML attribute (e.g.
    callbacks). Unsupported props are silently skipped.

    Args:
        props: Iterable of ``"name:value"`` strings.

    Returns:
        A space-prefixed attribute string, e.g. ``' class="foo" id="x"'``.
        Empty string when no static attributes survive.
    """
    out: list[str] = []
    for entry in props:
        text = str(entry)
        if ":" not in text:
            continue
        name, _, value = text.partition(":")
        name = name.strip()
        value = value.strip()
        if not name or name.startswith(("on", "ref")):
            continue
        attr_name = "class" if name == "className" else name
        # Only accept props whose value is a string literal.
        if len(value) >= 2 and (
            (value[0] == '"' and value[-1] == '"')
            or (value[0] == "'" and value[-1] == "'")
        ):
            out.append(f" {attr_name}={value}")
        # Drop everything else (callbacks, dynamic vars, etc.)
    return "".join(out)


def _render_props_as_jsx_attrs(props: Iterable[str]) -> str:
    """Render component props as JSX attributes for an island tag.

    Unlike :func:`_render_props_as_attrs`, this preserves React-style
    attribute names (``className`` stays ``className``) and supports
    boolean / numeric literal props by wrapping them in ``{...}`` so they
    survive the JSX parser. Static-string props pass through verbatim.

    State-driven values (anything that isn't a JSON-shaped literal) are
    dropped — those couldn't be evaluated server-side anyway and would
    produce a build error if emitted as JSX.

    Args:
        props: Iterable of ``"name:value"`` strings from the component's
            render dict.

    Returns:
        A space-prefixed attribute string (e.g.
        ``' variant="ghost" size="xs" nativeButton={true}'``), empty when
        no static props survive.
    """
    out: list[str] = []
    for entry in props:
        text = str(entry)
        if ":" not in text:
            continue
        name, _, value = text.partition(":")
        name = name.strip()
        value = value.strip()
        if not name or name.startswith(("on", "ref")):
            continue
        if len(value) >= 2 and (
            (value[0] == '"' and value[-1] == '"')
            or (value[0] == "'" and value[-1] == "'")
        ):
            out.append(f" {name}={value}")
            continue
        if value in ("true", "false"):
            out.append(f" {name}={{{value}}}")
            continue
        # Numeric literal (int or float; allow leading minus).
        numeric = value.removeprefix("-")
        if numeric and numeric.replace(".", "", 1).isdigit():
            out.append(f" {name}={{{value}}}")
    return "".join(out)


def _emit_island_module(
    *, route: str, island_name: str, export_name: str, import_source: str
) -> AstroPageArtifact:
    """Emit a per-route React island module that re-exports a component.

    The per-island ``.tsx`` lives at
    ``src/reflex/islands/<route>/<island_name>.tsx``. It is a single-line
    re-export so Astro can mount the underlying component with
    ``client:visible`` from the inline ``.astro`` markup. The shared
    runtime is SSR-safe (router adapter has sane server-side defaults;
    React Contexts default to empty values), so no lazy/Suspense
    scaffolding is needed.

    The ``import_source`` is taken verbatim from the component's
    ``library`` attribute. Vite/Astro's ``$/`` alias resolves to the
    ``.web/`` root, so paths like ``"$/utils/components"`` or
    ``"$/public/components/GradientButton"`` work from any depth without
    relative-path computation.

    Args:
        route: The Reflex route the island lives under.
        island_name: PascalCase name used as the JSX tag in the .astro
            file and as the module's file name.
        export_name: Named export to import from ``import_source``
            (the component's ``tag``).
        import_source: Module specifier to re-export from. Typically
            comes straight from the component's ``library`` attribute.

    Returns:
        The :class:`AstroPageArtifact` for the per-island module.
    """
    module_path = astro_island_module_path(route, island_name)
    contents = (
        '// Generated by Reflex (frontend_target="astro"). Do not edit.\n'
        f'export {{ {export_name} as default }} from "{import_source}";\n'
    )
    return AstroPageArtifact(path=module_path, contents=contents)


def _render_node(
    rendered: Any,
    *,
    island_lookup: dict[int, tuple[str, str, str]],
    indent: str,
    out: list[str],
) -> None:
    """Recursively render one node of the Reflex render dict to Astro markup.

    Args:
        rendered: The render dict for the current node.
        island_lookup: Maps ``id(component)`` of each detected island to
            ``(component_name, directive, media_or_empty)`` for emission.
        indent: Two-space indent prefix for the current depth.
        out: Output buffer; lines are appended in order.
    """
    if rendered is None:
        return
    if isinstance(rendered, str):
        # Bare string contents — escape and emit.
        text = rendered
        if _looks_like_state_expression(text):
            out.append(f"{indent}<!-- reflex islands: dropped state expression -->")
            return
        unquoted = _strip_quotes(text)
        if unquoted.strip() in ("null", "undefined"):
            # ``cond(... , None)`` and similar absent children render as the
            # bare JS literal ``null``/``undefined`` in the compiled tree.
            return
        out.append(indent + html.escape(unquoted))
        return
    if not isinstance(rendered, dict):
        return

    # Island substitution — checked via the dict's own component identity if
    # the caller threaded it through; here we look at the explicit
    # placeholder name we inserted in :func:`render_islands_page`.
    if "_island_placeholder" in rendered:
        component_name, directive, media = rendered["_island_placeholder"]
        if media:
            attr_str = f"{directive}={{{media!r}}}".replace("'", '"')
        elif directive == "client:only":
            attr_str = 'client:only="react"'
        else:
            attr_str = directive
        # Forward the component's static props (``variant``, ``size``,
        # ``className``, etc.) through the island tag so Astro's SSR pass
        # invokes the React component with the right shape. Without this,
        # every island would render with the component's default props
        # — e.g. every ``GradientButton`` would show as ``variant="primary"``
        # regardless of how the page declared it.
        attr_str += _render_props_as_jsx_attrs(rendered.get("_island_props", []))
        # Auto-memo wrappers (and several CustomComponents) take ``children``
        # and inject them into their JSX output. Pass any rendered children
        # through Astro's slot mechanism so the SSR pass produces real HTML
        # inside the island instead of an empty shell.
        children = rendered.get("children", []) or []
        if not children:
            out.append(f"{indent}<{component_name} {attr_str} />")
            return
        out.append(f"{indent}<{component_name} {attr_str}>")
        child_indent = indent + "  "
        for child in children:
            _render_node(
                child, island_lookup=island_lookup, indent=child_indent, out=out
            )
        out.append(f"{indent}</{component_name}>")
        return

    # Plain text contents.
    if (contents := rendered.get("contents")) is not None:
        text = str(contents)
        if _looks_like_state_expression(text):
            out.append(f"{indent}<!-- reflex islands: dropped state expression -->")
            return
        unquoted = _strip_quotes(text)
        if unquoted.strip() in ("null", "undefined"):
            return
        out.append(indent + html.escape(unquoted))
        return

    # Conditional / iterable / match are state-driven; they should have been
    # promoted to an island by the auto-memo pass. Defensive comment if not.
    if {"iterable", "cond_state", "match_cases"} & set(rendered.keys()):
        out.append(
            f"{indent}<!-- reflex islands: state-dependent form not promoted -->"
        )
        return

    name = _strip_quotes(rendered.get("name", "Fragment"))
    children = rendered.get("children", []) or []
    if name == "Fragment":
        for child in children:
            _render_node(child, island_lookup=island_lookup, indent=indent, out=out)
        return

    # Drop any non-HTML React component reference that isn't an island —
    # those should have been wrapped in an island already, but if not we emit
    # a comment so the build is not broken.
    if not _is_html_tag_name(name):
        out.append(f"{indent}<!-- reflex islands: unrendered component {name} -->")
        return

    attrs = _render_props_as_attrs(rendered.get("props", []))
    if not children:
        out.append(f"{indent}<{name}{attrs} />")
        return
    out.append(f"{indent}<{name}{attrs}>")
    child_indent = indent + "  "
    for child in children:
        _render_node(child, island_lookup=island_lookup, indent=child_indent, out=out)
    out.append(f"{indent}</{name}>")


def _island_target_from_component(node: Any) -> tuple[str, str] | None:
    """Return ``(export_name, import_source)`` for an islandable component.

    Resolves what the islands renderer needs to emit a per-route island
    module: the React export name (the component's ``tag``) and the
    module specifier to re-export from (the component's ``library``).

    Recognized as island roots:

    - :class:`reflex.experimental.memo.ExperimentalMemoComponent` —
      compile-time auto-memo wrappers; ``library`` is
      ``$/utils/components/<tag>``.
    - :class:`reflex_base.components.component.CustomComponent` — the
      legacy ``@rx.memo`` decorator output; ``library`` is the
      ``$/utils/components`` barrel.
    - Any other ``rx.Component`` whose ``tag`` is non-empty PascalCase
      and whose ``library`` is local generated code (starts with ``$/``
      or ``./``). This covers user-authored React components like
      ``GradientButton`` that ship their own ``.tsx`` under
      ``public/components/``.

    Rejected (returns ``None``):

    - HTML elements (lowercase ``tag``) and ``Fragment``.
    - Components without a ``tag`` or ``library``.
    - Components imported from third-party NPM packages
      (``library`` does not start with ``$/`` or ``./``). Re-exporting
      a Radix or Recharts symbol verbatim would not produce a valid
      Reflex-compatible island; those components must opt in via
      ``provides_hydrated_context = True`` so an ancestor island wraps
      them instead.

    Args:
        node: The component to inspect.

    Returns:
        A ``(export_name, import_source)`` tuple, or ``None`` if the
        component cannot be safely promoted to an island.
    """
    tag = getattr(node, "tag", None)
    library = getattr(node, "library", None)
    if (
        not isinstance(tag, str)
        or not tag
        or tag == "Fragment"
        or tag[0].islower()
        or not isinstance(library, str)
        or not library
    ):
        return None
    if not library.startswith(("$/", "./")):
        return None
    return tag, library


def _replace_islands_in_render(
    component: Any,
    *,
    placements_by_id: dict[int, tuple[str, str, str | None]],
) -> Any:
    """Return a render dict where island roots are replaced with placeholders.

    Walks the component (not the render dict) so we can use ``id()`` against
    placement records, then renders each non-island subtree via the regular
    ``component.render()`` and substitutes a placeholder dict for islands.

    Args:
        component: The root component whose subtree is being prepared for
            static HTML emission.
        placements_by_id: Map from ``id(component)`` of each island root to
            ``(island_name, directive, media)``.

    Returns:
        A render dict (or string) suitable for :func:`_render_node`.
    """
    # Strings and primitives pass through unchanged.
    if not hasattr(component, "render") or not hasattr(component, "children"):
        # Fall back to whatever the component would render to.
        return component.render() if hasattr(component, "render") else str(component)

    placement = placements_by_id.get(id(component))
    if placement is not None:
        island_name, directive, media = placement
        # Capture the component's own props so the island tag carries the
        # variant/size/className the user declared. ``component.render()``
        # produces the canonical render dict; we only need its ``props``
        # list to forward as JSX attributes.
        island_props = component.render().get("props", []) or []
        # Recurse into the island root's children so they survive as
        # nested Astro markup inside the island's slot. Auto-memo
        # wrappers take ``children`` as a prop and inject them into
        # their JSX; without this, the SSR'd island is an empty shell.
        rendered_children = [
            _replace_islands_in_render(child, placements_by_id=placements_by_id)
            for child in (component.children or [])
        ]
        return {
            "_island_placeholder": (island_name, directive, media),
            "_island_props": island_props,
            "children": rendered_children,
        }

    # Recurse children, then build an unrendered tree dict ourselves so we
    # can keep the placeholder replacements.
    rendered_children = [
        _replace_islands_in_render(child, placements_by_id=placements_by_id)
        for child in (component.children or [])
    ]
    base = component.render()
    # Keep tag/props from the rendered dict, override children with the
    # mixed (HTML / placeholder) list.
    return {
        **base,
        "children": rendered_children,
    }


def render_islands_page(
    *,
    route: str,
    root: BaseComponent,
) -> IslandsRenderResult:
    """Render an islands-mode page to inline Astro HTML + per-island modules.

    Args:
        route: The Reflex route (``/``-prefixed).
        root: The compiled root component for the page.

    Returns:
        An :class:`IslandsRenderResult`. ``body`` is empty when there are no
        islands and no static content (caller may treat this as a
        zero-content page and downgrade to ``static`` mode).
    """
    placements = classify_islands(root)
    placements_by_id: dict[int, tuple[str, str, str | None]] = {}
    island_modules: list[AstroPageArtifact] = []
    imports: list[str] = []
    directives: list[str] = []
    used_names: set[str] = set()

    # Walk the component tree to find island roots and assign each a unique
    # PascalCase JSX name.
    def walk_for_islands(comp: Any) -> None:
        if comp is None:
            return
        target = _island_target_from_component(comp)
        if target is not None:
            export_name, import_source = target
            island_name = export_name
            # Disambiguate when the same export appears multiple times on
            # the same page (e.g. several ``<GradientButton/>`` instances).
            base = island_name
            counter = 1
            while island_name in used_names:
                counter += 1
                island_name = f"{base}_{counter}"
            used_names.add(island_name)
            # ``client:visible`` is the default: Astro defers BOTH the
            # script download AND the hydration until the island scrolls
            # into the viewport. The per-island module is SSR-safe (router
            # adapter + React Contexts have sane server-side defaults), so
            # SSR succeeds without touching Reflex's state context, and
            # the heavy runtime chunks never enter the network tab unless
            # the island is actually visible.
            directive = "client:visible"
            placements_by_id[id(comp)] = (island_name, directive, None)
            island_modules.append(
                _emit_island_module(
                    route=route,
                    island_name=island_name,
                    export_name=export_name,
                    import_source=import_source,
                )
            )
            module_path = astro_island_module_path(route, island_name)
            island_depth = max(1, len(_split_route(route)))
            rel_to_src = "../" * island_depth
            relative_import = (
                rel_to_src + module_path[len("src/") :]
                if module_path.startswith("src/")
                else module_path
            )
            imports.append(f'import {island_name} from "{relative_import}";')
            directives.append(directive)
            # Fall through and descend: nested islands inside this one
            # (e.g. inner auto-memo wrappers) get their own per-route
            # modules and Astro emits them as nested ``<astro-island>``
            # references inside the parent's slot.
        # Descend.
        children = getattr(comp, "children", None) or []
        if isinstance(children, (list, tuple)):
            for child in children:
                walk_for_islands(child)

    walk_for_islands(root)

    # If we found no auto-memo islands, fall back to using the classifier's
    # placements so Path B / explicit ``rx.island(...)`` still work. (Their
    # render-tree integration is a follow-up; for v1 we mark each as a
    # placeholder under the layout.)
    if not placements_by_id:
        for placement in placements:
            placements_by_id[id(placement)] = (
                placement.component_name,
                placement.directive,
                placement.media,
            )

    # Build the static-HTML body.
    swapped = _replace_islands_in_render(root, placements_by_id=placements_by_id)
    out_lines: list[str] = []
    _render_node(swapped, island_lookup={}, indent="  ", out=out_lines)
    body = "\n".join(out_lines)
    _ = placements  # placement records remain useful for future tightening
    return IslandsRenderResult(
        body=body,
        imports=tuple(imports),
        island_modules=tuple(island_modules),
        directives=tuple(directives),
    )


def _split_route(route: str) -> list[str]:
    """Return non-empty path segments of a ``/``-prefixed route."""
    return [seg for seg in route.split("/") if seg]
