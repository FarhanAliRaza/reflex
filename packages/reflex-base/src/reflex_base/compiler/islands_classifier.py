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
        directive: Astro client directive to emit at the boundary.
        reason: Why this node was promoted to an island.
        media: Optional media query for ``client:visible``-style placement.
        client_only: When True, render with ``client:only="react"``.
        node_id: ``id()`` of the underlying component, used by the walker
            to suppress nested islands. Not for downstream consumption.
    """

    component_name: str
    directive: Literal["client:load", "client:idle", "client:visible", "client:only"]
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
        """
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
    """Return True if ``node`` directly uses Reflex state.

    Detects:
    - explicit event triggers on the component,
    - own props with state-bound ``VarData``,
    - ``ExperimentalMemoComponent`` wrappers — those are emitted by the
      auto-memoize pass and only exist when the underlying subtree is
      stateful, so they are reliable Path A markers post-walk.

    Args:
        node: The component to inspect.

    Returns:
        Whether the node carries any direct state signal.
    """
    # Auto-memo wrappers are produced only for stateful subtrees. By the time
    # the islands classifier runs the original state-bearing leaves have been
    # replaced by these wrappers, so the wrapper itself is the surviving signal.
    try:
        from reflex.experimental.memo import ExperimentalMemoComponent

        if isinstance(node, ExperimentalMemoComponent):
            return True
    except ImportError:
        pass

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
        if var_data is not None and getattr(var_data, "state", None):
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

    Detects: state signals (Path A), Path B metadata, and explicit
    :class:`IslandComponent` wrappers.

    Args:
        node: The root to walk.

    Returns:
        Whether the subtree contains at least one island-worthy node.
    """
    from reflex_base.components.island import IslandComponent

    if isinstance(node, IslandComponent):
        return True
    if _has_state_signal(node) or _has_island_metadata(node):
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

    Suppression rule: when a node becomes an island root, descendants are
    not independently classified — they ride inside that island's React
    tree.

    Args:
        node: The root to walk.
        name_counter: Mutable counter used to make duplicate component
            names unique (e.g. ``"Card"`` -> ``"Card_2"``).

    Yields:
        Each detected island root, in pre-order.
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

    # If a child needs an island (state signal, Path B metadata, or an
    # explicit wrapper), descend so the child's smallest enclosing subtree
    # gets promoted.
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
