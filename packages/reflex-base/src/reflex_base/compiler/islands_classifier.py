"""Auto-placement of client islands on ``render_mode="islands"`` pages.

This module implements deterministic island-boundary placement:

- **Path A (tree signals).** Any node that uses Reflex state — vars with
  ``var_data``, event triggers on the component, or any descendant carrying
  the same — is promoted to the smallest enclosing subtree that hydrates.
- **Path B (class metadata).** Any class declaring ``requires_hydration``,
  ``provides_hydrated_context``, or ``client_only`` becomes an island root.
  The boundary covers the entire subtree.
- **User overrides.** ``rx.island(...)`` wrappers are honored verbatim;
  the wrapper's ``IslandSpec`` selects the directive and ``client_only``
  behavior. A nested ``rx.island(...)`` inside another island is rejected
  upstream by :func:`reflex_base.components.island.island`.
- **Suppression.** Once a node is marked as an island root, descendants that
  would also qualify do not produce additional islands; they ride along
  inside the parent island's React tree.

The walker yields :class:`AstroIslandPlacement` records — pure data — so
callers can map them onto :class:`reflex_base.compiler.astro.AstroIsland`
instances and emit them through the normal Astro page emitter.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Literal

from reflex_base.compiler.astro import AstroIsland

if TYPE_CHECKING:
    from reflex_base.components.component import BaseComponent

PlacementReason = Literal[
    "explicit-island",  # rx.island(...) wrapper
    "requires-hydration",  # ClassVar metadata
    "provides-hydrated-context",  # ClassVar metadata
    "client-only",  # ClassVar metadata
    "tree-signal",  # state var or event trigger
    "ssr-only",  # auto-memo wrapper with no runtime state — SSR, ship no JS
]

_STRATEGY_DIRECTIVE: dict[
    str, Literal["client:load", "client:idle", "client:visible"]
] = {
    "load": "client:load",
    "idle": "client:idle",
    "visible": "client:visible",
}


@dataclasses.dataclass(frozen=True)
class AstroIslandPlacement:
    """One auto-placed island boundary detected by the classifier.

    Attributes:
        component_name: A stable PascalCase identifier for the island (used
            as the React module export name and the JSX tag in the .astro file).
        directive: Astro client directive to emit at the boundary, or
            ``None`` for ``"ssr-only"`` placements (Astro renders the
            component server-side and ships no JS for it).
        reason: Why this node was promoted to an island.
        media: Optional media query for ``client:visible``-style placement.
        client_only: When True, render with ``client:only="react"``.
        node_id: ``id()`` of the underlying component, used by the walker
            to suppress nested islands. Not for downstream consumption.
    """

    component_name: str
    directive: (
        Literal["client:load", "client:idle", "client:visible", "client:only"] | None
    )
    reason: PlacementReason
    media: str | None = None
    client_only: bool = False
    node_id: int = 0

    def to_astro_island(self, *, module_path: str) -> AstroIsland:
        """Convert to a downstream :class:`AstroIsland` record.

        Args:
            module_path: The Astro-relative import path for the island's
                generated React module.

        Returns:
            An :class:`AstroIsland` ready for the Astro page emitter.

        Raises:
            ValueError: If the placement is ``"ssr-only"`` — those are not
                hydrating islands and must not flow through
                :class:`AstroIsland`, which mandates a client directive.
        """
        if self.directive is None:
            msg = (
                f"AstroIslandPlacement(reason={self.reason!r}) has no client "
                "directive and cannot be converted to AstroIsland. SSR-only "
                "placements are emitted directly by the islands renderer."
            )
            raise ValueError(msg)
        return AstroIsland(
            component_name=self.component_name,
            module_path=module_path,
            directive=self.directive,
            media=self.media,
        )


def _component_class_name(node: Any) -> str:
    """Best-effort PascalCase name for a component instance.

    Args:
        node: The component-like value.

    Returns:
        The class name; falls back to ``type(...)__name__`` for non-classes.
    """
    cls = getattr(node, "__class__", None)
    return cls.__name__ if cls is not None else type(node).__name__


def _has_state_signal(node: Any) -> bool:
    """Return True if ``node`` directly carries runtime state.

    Detects:
    - explicit event triggers on the component,
    - own props with ``VarData.state`` set (i.e. the prop is bound to
      Reflex state and changes after mount).

    Auto-memo wrappers (``ExperimentalMemoComponent``) deliberately do not
    auto-qualify here. Auto-memoize fires on any ``VarData`` — including
    pure build-time signals such as icon imports — so the wrapper alone
    is not a reliable runtime-state marker. Callers that need to inspect
    a memo wrapper must consult the wrapper's ``_memoized_source`` via
    :func:`_memo_subtree_has_runtime_state`.

    Args:
        node: The component to inspect.

    Returns:
        Whether the node carries any direct runtime-state signal.
    """
    triggers = getattr(node, "event_triggers", None)
    if triggers:
        return True
    get_vars = getattr(node, "_get_vars", None)
    if not callable(get_vars):
        return False
    try:
        vars_iter = get_vars(include_children=False)
    except TypeError:
        # Some lightweight components do not accept the kwarg.
        return False
    if not vars_iter or not hasattr(vars_iter, "__iter__"):
        return False
    for prop_var in vars_iter:  # pyright: ignore[reportGeneralTypeIssues]
        get_var_data = getattr(prop_var, "_get_all_var_data", None)
        if not callable(get_var_data):
            continue
        var_data = get_var_data()
        if var_data is None:
            continue
        # Only state-bound vars qualify as runtime signals; pure import-only
        # var_data is a build-time bundling hint with no client behavior.
        if getattr(var_data, "state", None):
            return True
    return False


def _is_memo_wrapper(node: Any) -> bool:
    """Return True if ``node`` is an auto-memoize wrapper.

    Args:
        node: The component to inspect.

    Returns:
        Whether ``node`` is an :class:`ExperimentalMemoComponent` instance
        produced by the compile-time auto-memoize plugin.
    """
    try:
        from reflex.experimental.memo import ExperimentalMemoComponent
    except ImportError:
        return False
    return isinstance(node, ExperimentalMemoComponent)


def _memo_subtree_has_runtime_state(node: Any) -> bool:
    """Walk a memoized component subtree checking for actual runtime state.

    Decides whether an auto-memoize wrapper actually needs client-side
    React hydration. Event triggers and ``VarData.state``-bound props
    qualify; pure build-time ``var_data`` (icon imports, hook-only
    declarations attached to inert markup) does not.

    Recurses through nested memo wrappers via their ``_memoized_source``
    reference so an outer memo containing a stateful inner memo correctly
    propagates the hydration need.

    Args:
        node: The root of the subtree to check.

    Returns:
        True when the subtree contains any runtime-state signal; False when
        it can safely render server-side as static HTML.
    """
    if node is None:
        return False
    if _is_memo_wrapper(node):
        source = getattr(node, "_memoized_source", None)
        if source is None:
            # No visibility — be conservative and hydrate.
            return True
        return _memo_subtree_has_runtime_state(source)
    if _has_state_signal(node):
        return True
    children = getattr(node, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            if _memo_subtree_has_runtime_state(child):
                return True
    return False


def _has_island_metadata(node: Any) -> bool:
    """Return True if ``node`` carries Path B class-level metadata.

    Args:
        node: The component to inspect.

    Returns:
        Whether the node declares any of the hydration flags.
    """
    return bool(
        getattr(node, "client_only", False)
        or getattr(node, "provides_hydrated_context", False)
        or getattr(node, "requires_hydration", False)
    )


def _subtree_needs_island(node: Any) -> bool:
    """Return True if ``node`` or any descendant should be promoted to an island.

    Detects: state signals (Path A), Path B metadata, explicit
    :class:`IslandComponent` wrappers, and auto-memo wrappers (which need
    a placement either as a hydrating island or as an SSR-only Astro
    component reference).

    Args:
        node: The root to walk.

    Returns:
        Whether the subtree contains at least one node that requires a
        dedicated placement.
    """
    from reflex_base.components.island import IslandComponent

    if isinstance(node, IslandComponent):
        return True
    if _has_state_signal(node) or _has_island_metadata(node):
        return True
    if _is_memo_wrapper(node):
        return True
    children = getattr(node, "children", None)
    if not isinstance(children, (list, tuple)):
        return False
    return any(_subtree_needs_island(child) for child in children)


# Backwards-compatible alias used by tests / external callers.
_subtree_has_state_signal = _subtree_needs_island


def _placement_for_metadata(
    node: Any, name: str, node_id: int
) -> AstroIslandPlacement | None:
    """Decide whether a node's class metadata triggers an island.

    Args:
        node: The component to inspect.
        name: The component class name (for the generated identifier).
        node_id: ``id(node)``.

    Returns:
        A placement record when the metadata flags an island, otherwise None.
    """
    if getattr(node, "client_only", False):
        return AstroIslandPlacement(
            component_name=name,
            directive="client:only",
            reason="client-only",
            client_only=True,
            node_id=node_id,
        )
    if getattr(node, "provides_hydrated_context", False):
        return AstroIslandPlacement(
            component_name=name,
            directive="client:load",
            reason="provides-hydrated-context",
            node_id=node_id,
        )
    if getattr(node, "requires_hydration", False):
        return AstroIslandPlacement(
            component_name=name,
            directive="client:load",
            reason="requires-hydration",
            node_id=node_id,
        )
    return None


def _placement_for_island_wrapper(
    node: Any, name: str, node_id: int
) -> AstroIslandPlacement | None:
    """Decide the placement for an explicit :class:`IslandComponent` wrapper.

    Args:
        node: The wrapped component (must be an ``IslandComponent``).
        name: The inner component class name.
        node_id: ``id(node)``.

    Returns:
        A placement record honoring the user's :class:`IslandSpec`.
    """
    from reflex_base.components.island import IslandComponent

    if not isinstance(node, IslandComponent):
        return None
    spec = node.spec
    media: str | None = None
    directive: Literal["client:load", "client:idle", "client:visible", "client:only"]
    if spec.client_only:
        directive = "client:only"
    elif isinstance(spec.hydrate, str):
        directive = _STRATEGY_DIRECTIVE[spec.hydrate]
    else:
        directive = "client:visible"
        media = spec.hydrate.get("media")
    inner_name = _component_class_name(node.component)
    return AstroIslandPlacement(
        component_name=inner_name,
        directive=directive,
        reason="explicit-island",
        media=media,
        client_only=spec.client_only,
        node_id=node_id,
    )


def _iter_islands(
    node: Any,
    *,
    name_counter: dict[str, int],
) -> Iterator[AstroIslandPlacement]:
    """Walk the tree once and yield one placement per island boundary.

    Suppression rule: when a node becomes a hydrating island root,
    descendants are not independently classified — they ride inside that
    island's React tree. ``"ssr-only"`` placements are an exception: they
    do not hydrate, so descendants still need their own placements when
    they carry runtime state.

    Args:
        node: The root to walk.
        name_counter: Mutable counter used to make duplicate component
            names unique (e.g. ``"Card"`` -> ``"Card_2"``).

    Yields:
        Each detected placement, in pre-order.
    """
    if node is None:
        return

    name = _component_class_name(node)
    nid = id(node)

    # Explicit user-authored islands win first.
    explicit = _placement_for_island_wrapper(node, name, nid)
    if explicit is not None:
        yield _make_unique(explicit, name_counter)
        return

    # Class-level metadata wins next.
    metadata = _placement_for_metadata(node, name, nid)
    if metadata is not None:
        yield _make_unique(metadata, name_counter)
        return

    # Auto-memo wrappers: split into hydrating islands vs SSR-only based on
    # whether the underlying component subtree carries runtime state.
    if _is_memo_wrapper(node):
        # Use the memo's tag (matches its export name in the generated React
        # module) so the .astro file's import resolves correctly. The Python
        # class name carries the dynamic-subclass prefix and would not match.
        memo_name = getattr(node, "tag", None) or name
        source = getattr(node, "_memoized_source", None)
        if source is None or _memo_subtree_has_runtime_state(source):
            yield _make_unique(
                AstroIslandPlacement(
                    component_name=memo_name,
                    directive="client:idle",
                    reason="tree-signal",
                    node_id=nid,
                ),
                name_counter,
            )
            return
        # No runtime state — Astro server-renders the component, ships no
        # JS for it. Descend so children with their own state get their own
        # placements (the wrapper's ``{children}`` slot is filled by the
        # page-side subtree, which the walker already handles).
        yield _make_unique(
            AstroIslandPlacement(
                component_name=memo_name,
                directive=None,
                reason="ssr-only",
                node_id=nid,
            ),
            name_counter,
        )
        children = getattr(node, "children", None)
        if isinstance(children, (list, tuple)):
            for child in children:
                if _subtree_needs_island(child):
                    yield from _iter_islands(child, name_counter=name_counter)
        return

    # Tree signals: the smallest enclosing subtree wins.
    if _has_state_signal(node):
        yield _make_unique(
            AstroIslandPlacement(
                component_name=name,
                directive="client:load",
                reason="tree-signal",
                node_id=nid,
            ),
            name_counter,
        )
        return

    # If a child needs a placement (state signal, Path B metadata, an
    # explicit wrapper, or a memo wrapper), descend so the child's
    # smallest enclosing subtree gets handled.
    children = getattr(node, "children", None)
    if not isinstance(children, (list, tuple)):
        return
    for child in children:
        if _subtree_needs_island(child):
            yield from _iter_islands(child, name_counter=name_counter)


def _make_unique(
    placement: AstroIslandPlacement,
    counter: dict[str, int],
) -> AstroIslandPlacement:
    """Disambiguate repeated component names across the page.

    Two ``Card`` components on the same page need distinct module names
    so the Astro emitter does not collide them. The first occurrence keeps
    its name; subsequent occurrences get a numeric suffix.

    Args:
        placement: The original placement record.
        counter: A dict tracking per-name occurrence counts. Mutated.

    Returns:
        The placement (unchanged) for the first occurrence, or a new record
        with a suffixed ``component_name`` for repeats.
    """
    base = placement.component_name
    counter[base] = counter.get(base, 0) + 1
    if counter[base] == 1:
        return placement
    return dataclasses.replace(placement, component_name=f"{base}_{counter[base]}")


def classify_islands(root: BaseComponent) -> list[AstroIslandPlacement]:
    """Top-level entry point: classify the page tree into island placements.

    Args:
        root: The compiled root component for the page.

    Returns:
        A list of :class:`AstroIslandPlacement` records, in pre-order.
        Empty when the page has no stateful or hydration-flagged nodes.
    """
    name_counter: dict[str, int] = {}
    return list(_iter_islands(root, name_counter=name_counter))
