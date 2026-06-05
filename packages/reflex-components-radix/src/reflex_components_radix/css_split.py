"""Split the monolithic Radix Themes stylesheet into per-component chunks.

Radix Themes ships a single compiled ``styles.css`` (~800 KB). Loading it whole
means a page that uses one Button still pays for every component's CSS. This
module splits that bundle into a shared base (design tokens, color scales,
reset, layout/utility classes and the internal ``rt-Base*`` foundations) plus
one chunk per Radix component, so the compiler can import only the chunks for
components actually mounted on a page and let the bundler tree-shake the rest.

The split is **lossless**: every declaration in the source bundle is preserved
in exactly the chunks whose component namespaces reference it (or in the shared
base when it references none), so any mounted subset receives a superset of the
rules that could match its DOM and renders pixel-identically to the full bundle.

A component namespace is owned by the source file that defines it in its own
rules, read from the package's ``src/components`` directory (which ships
alongside the compiled bundle). The internal ``rt-Base*`` foundations and any
namespace not owned by a real component chunk fall through to the shared base,
so every rule remains reachable from some imported chunk.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

SHARED_CHUNK = "_shared"
# Directory prefix (within the chunk namespace) for per-accent color chunks.
COLOR_CHUNK_PREFIX = "colors/"

# Radix accent color scales. Tree-shaken per used accent; the gray scales
# (gray/mauve/slate/sage/olive/sand) stay shared to avoid the accent<->gray
# auto-pairing, and are comparatively small.
ACCENT_COLORS = (
    "tomato",
    "red",
    "ruby",
    "crimson",
    "pink",
    "plum",
    "purple",
    "violet",
    "iris",
    "indigo",
    "blue",
    "cyan",
    "teal",
    "jade",
    "green",
    "grass",
    "brown",
    "orange",
    "sky",
    "mint",
    "lime",
    "yellow",
    "amber",
    "gold",
    "bronze",
)

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def radix_chunk_name(tag: str) -> str:
    """Map a Radix Themes component tag to its CSS chunk name.

    Mirrors Radix's own kebab-case source file naming, e.g. ``IconButton`` ->
    ``icon-button`` and ``TextField.Root`` -> ``text-field``.

    Args:
        tag: The component tag (possibly dotted for sub-components).

    Returns:
        The chunk name (source file stem) for the component.
    """
    return _CAMEL_BOUNDARY.sub("-", tag.split(".")[0]).lower()


_COMPONENT_CLASS = re.compile(r"\.rt-[A-Z][A-Za-z0-9]*")
_BASE_CLASS_PREFIX = ".rt-Base"
_AT_RULE = re.compile(r"^@([A-Za-z-]+)")
# At-rules whose blocks contain component rules and must be split and rewrapped.
_NESTING_AT_RULES = {"media", "supports", "layer", "container"}


def _split_top_level_nodes(css: str) -> list[str]:
    """Split CSS into top-level nodes, respecting strings, comments and braces.

    Args:
        css: The CSS text to split.

    Returns:
        The list of top-level rules and at-rules (each including its block).
    """
    nodes: list[str] = []
    i = 0
    n = len(css)
    depth = 0
    start = 0
    in_str: str | None = None
    while i < n:
        c = css[i]
        if in_str is not None:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
            i += 1
            continue
        if c in "\"'":
            in_str = c
        elif c == "/" and i + 1 < n and css[i + 1] == "*":
            end = css.find("*/", i + 2)
            i = (end + 2) if end != -1 else n
            continue
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                nodes.append(css[start : i + 1])
                start = i + 1
        elif c == ";" and depth == 0:
            nodes.append(css[start : i + 1])
            start = i + 1
        i += 1
    tail = css[start:].strip()
    if tail:
        nodes.append(tail)
    return [stripped for node in nodes if (stripped := node.strip())]


def _prelude_and_block(node: str) -> tuple[str | None, str | None]:
    """Split a node into its prelude and block body.

    Args:
        node: A single CSS node.

    Returns:
        The ``(prelude, block_body)`` pair, or ``(None, None)`` if the node has
        no block (e.g. a bare ``@import``).
    """
    brace = node.find("{")
    if brace == -1 or not node.endswith("}"):
        return None, None
    return node[:brace].strip(), node[brace + 1 : -1]


def _own_namespaces(text: str) -> set[str]:
    """Get the component namespaces defined by a source file's own rules.

    Args:
        text: The source CSS text.

    Returns:
        The set of ``.rt-*`` component classes, excluding ``@import``ed files.
    """
    own = re.sub(r"@import[^;]+;", "", text)
    return set(_COMPONENT_CLASS.findall(own))


def _build_namespace_index(
    components_dir: Path, component_stems: set[str] | None
) -> dict[str, set[str]]:
    """Map each non-base component namespace to the chunk(s) that own it.

    A namespace is owned by the source file that defines it in its own rules.
    ``rt-Base*`` namespaces and owners outside ``component_stems`` are excluded
    so their rules fall through to the shared base.

    Args:
        components_dir: The Radix Themes ``src/components`` directory.
        component_stems: The stems that map to real importable chunks, or
            ``None`` to allow every non-internal source file to own a chunk.

    Returns:
        Map of ``.rt-Name`` class -> set of owning chunk names (source stems).
    """
    namespace_to_chunks: dict[str, set[str]] = {}
    for path in components_dir.rglob("*.css"):
        rel = path.relative_to(components_dir).as_posix()
        if rel.startswith("_internal/"):
            continue
        chunk = path.stem
        if component_stems is not None and chunk not in component_stems:
            continue
        for namespace in _own_namespaces(path.read_text(encoding="utf-8")):
            if namespace.startswith(_BASE_CLASS_PREFIX):
                continue
            namespace_to_chunks.setdefault(namespace, set()).add(chunk)
    return namespace_to_chunks


def _target_chunks(
    prelude: str, namespace_to_chunks: dict[str, set[str]]
) -> set[str] | None:
    """Determine which chunks a rule belongs to from its selector prelude.

    Args:
        prelude: The selector text of a style rule.
        namespace_to_chunks: The namespace ownership index.

    Returns:
        The set of chunk names the rule belongs to, or ``None`` for the shared
        base (when the prelude references no owned component namespace).
    """
    namespaces = set(_COMPONENT_CLASS.findall(prelude))
    if not namespaces:
        return None
    chunks: set[str] = set()
    for namespace in namespaces:
        chunks |= namespace_to_chunks.get(namespace, set())
    return chunks or None


def _split_declarations(block: str) -> list[str]:
    """Split a declaration block on top-level semicolons.

    Args:
        block: The body of a style rule (declarations only).

    Returns:
        The individual declarations, each keeping its trailing semicolon.
    """
    decls: list[str] = []
    depth = 0
    start = 0
    in_str: str | None = None
    i = 0
    n = len(block)
    while i < n:
        c = block[i]
        if in_str is not None:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
            i += 1
            continue
        if c in "\"'":
            in_str = c
        elif c in "({":
            depth += 1
        elif c in ")}":
            depth -= 1
        elif c == ";" and depth == 0:
            decls.append(block[start : i + 1])
            start = i + 1
        i += 1
    tail = block[start:].strip()
    if tail:
        decls.append(tail)
    return [d for d in decls if d.strip()]


_DECL_COLOR = re.compile(r"^\s*--([a-z]+)-")
_SELECTOR_ACCENT = re.compile(r"data-accent-color\s*=\s*['\"]?([a-z]+)")


def _partition_accent_node(
    node: str,
    accents: set[str],
    shared: list[str],
    buckets: dict[str, list[str]],
) -> None:
    """Route one shared node to the accent chunk(s) it concerns, else shared.

    Args:
        node: A CSS node from the shared base.
        accents: The accent color names to extract.
        shared: Accumulator for nodes that stay shared (mutated).
        buckets: Accumulator of accent -> nodes (mutated).
    """
    prelude, block = _prelude_and_block(node)
    if prelude is None:
        shared.append(node)
        return
    at_rule = _AT_RULE.match(prelude)
    if at_rule:
        if at_rule.group(1).lower() not in _NESTING_AT_RULES:
            shared.append(node)
            return
        inner_shared: list[str] = []
        inner_buckets: dict[str, list[str]] = defaultdict(list)
        for inner in _split_top_level_nodes(block or ""):
            _partition_accent_node(inner, accents, inner_shared, inner_buckets)
        if inner_shared:
            shared.append(prelude + " {\n" + "\n".join(inner_shared) + "\n}")
        for accent, rules in inner_buckets.items():
            buckets[accent].append(prelude + " {\n" + "\n".join(rules) + "\n}")
        return
    pinned = _SELECTOR_ACCENT.search(prelude)
    if pinned and pinned.group(1) in accents:
        buckets[pinned.group(1)].append(node)
        return
    keep: list[str] = []
    by_accent: dict[str, list[str]] = defaultdict(list)
    for decl in _split_declarations(block or ""):
        match = _DECL_COLOR.match(decl)
        if match and match.group(1) in accents:
            by_accent[match.group(1)].append(decl)
        else:
            keep.append(decl)
    if not by_accent:
        shared.append(node)
        return
    if keep:
        shared.append(prelude + " {" + "".join(keep) + "}")
    for accent, decls in by_accent.items():
        buckets[accent].append(prelude + " {" + "".join(decls) + "}")


def split_radix_css(
    compiled_css: str,
    components_dir: Path | None,
    component_stems: Iterable[str] | None = None,
    accent_colors: Iterable[str] | None = None,
) -> dict[str, str]:
    """Split the compiled Radix Themes bundle into shared and per-component chunks.

    Args:
        compiled_css: The contents of ``@radix-ui/themes/styles.css``.
        components_dir: The package's ``src/components`` directory used to map
            namespaces to components. When ``None`` or missing, the whole bundle
            is returned as the shared chunk (no splitting, still correct).
        component_stems: The chunk stems that components actually import. Each
            gets a chunk (empty if it owns no rules, so the import never 404s),
            and rules owned only by other source files fall to the shared base.
            When ``None``, every non-internal source file may own a chunk.
        accent_colors: Accent color names to lift out of the shared base into
            per-accent ``colors/<name>`` chunks (scale definitions plus the
            ``data-accent-color`` aliasing), so a page only loads the accents it
            uses. When ``None``, accents stay in the shared base.

    Returns:
        Map of chunk name -> CSS text. Always includes :data:`SHARED_CHUNK`;
        per-accent chunks are keyed ``colors/<name>``.
    """
    if components_dir is None or not components_dir.is_dir():
        return {SHARED_CHUNK: compiled_css}

    stems = set(component_stems) if component_stems is not None else None
    namespace_to_chunks = _build_namespace_index(components_dir, stems)
    buckets: dict[str, list[str]] = {SHARED_CHUNK: []}
    # Seed every importable stem so its chunk file always exists.
    for stem in stems or ():
        buckets[stem] = []

    def emit(chunk: str, node: str) -> None:
        buckets.setdefault(chunk, []).append(node)

    for node in _split_top_level_nodes(compiled_css):
        prelude, block = _prelude_and_block(node)
        if prelude is None:
            emit(SHARED_CHUNK, node)
            continue
        at_rule = _AT_RULE.match(prelude)
        if at_rule:
            if at_rule.group(1).lower() not in _NESTING_AT_RULES:
                # @keyframes, @font-face, etc. are component-agnostic.
                emit(SHARED_CHUNK, node)
                continue
            grouped: dict[str, list[str]] = {}
            for inner in _split_top_level_nodes(block or ""):
                inner_prelude, _ = _prelude_and_block(inner)
                if inner_prelude is None:
                    grouped.setdefault(SHARED_CHUNK, []).append(inner)
                    continue
                targets = _target_chunks(inner_prelude, namespace_to_chunks)
                for chunk in targets or (SHARED_CHUNK,):
                    grouped.setdefault(chunk, []).append(inner)
            for chunk, rules in grouped.items():
                emit(chunk, prelude + " {\n" + "\n".join(rules) + "\n}")
            continue
        targets = _target_chunks(prelude, namespace_to_chunks)
        for chunk in targets or (SHARED_CHUNK,):
            emit(chunk, node)

    buckets.setdefault(SHARED_CHUNK, [])

    accents = set(accent_colors) if accent_colors is not None else None
    if accents:
        new_shared: list[str] = []
        accent_buckets: dict[str, list[str]] = defaultdict(list)
        for node in buckets[SHARED_CHUNK]:
            _partition_accent_node(node, accents, new_shared, accent_buckets)
        buckets[SHARED_CHUNK] = new_shared
        # Seed every accent so its chunk file always exists for imports.
        for accent in accents:
            buckets[f"{COLOR_CHUNK_PREFIX}{accent}"] = accent_buckets.get(accent, [])

    return {chunk: "\n".join(nodes) + "\n" for chunk, nodes in buckets.items()}
