"""Client island override API for the Astro target.

`rx.island(...)` is an `islands`-mode override, not a correctness requirement.
The Astro compiler auto-places islands using Path A (tree signals) and Path B
(component metadata) from Master Task 2 of the Astro migration. `rx.island(...)`
is used only to:

- change the hydration strategy for an island (`"idle"`/`"visible"`/media query),
- widen a boundary to include sibling static content,
- force `client_only=True` on a subtree the compiler would otherwise prerender.

The wrapper is recorded as a structural marker on the wrapped component; the
actual `client:*` directive emission happens in the Astro page emitter (Master
Task 6). On the React Router target the wrapper is a no-op.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal

from reflex_base.utils.exceptions import CompileError

if TYPE_CHECKING:
    from reflex_base.components.component import Component


HydrateStrategy = Literal["load", "idle", "visible"]
HydrateMedia = Mapping[str, str]
HydrateOption = HydrateStrategy | HydrateMedia

_VALID_HYDRATE_STRATEGIES: tuple[str, ...] = ("load", "idle", "visible")


@dataclasses.dataclass(frozen=True)
class IslandSpec:
    """Compile-time descriptor for an explicit `rx.island(...)` override.

    Attached to a wrapped component via :class:`IslandComponent` and consulted
    by the Astro page emitter when placing `client:*` directives.

    Attributes:
        hydrate: The Astro hydration strategy. One of "load" (default), "idle",
            "visible", or a `{"media": "<query>"}` mapping.
        client_only: When True, the subtree is rendered with `client:only="react"`
            and is not prerendered to HTML.
    """

    hydrate: HydrateOption = "load"
    client_only: bool = False


def _validate_hydrate(hydrate: Any) -> HydrateOption:
    """Validate the `hydrate=` argument to :func:`island`.

    Args:
        hydrate: The user-supplied value.

    Returns:
        The normalized hydrate option.

    Raises:
        CompileError: If the value is not a known strategy string or a
            single-key media mapping.
    """
    if isinstance(hydrate, str):
        if hydrate == "load":
            return "load"
        if hydrate == "idle":
            return "idle"
        if hydrate == "visible":
            return "visible"
        msg = (
            f"Invalid hydrate={hydrate!r} for rx.island(...). "
            f"Expected one of {_VALID_HYDRATE_STRATEGIES} or "
            f"a {{'media': '<query>'}} mapping."
        )
        raise CompileError(msg)
    if isinstance(hydrate, Mapping):
        if set(hydrate.keys()) != {"media"} or not isinstance(
            hydrate.get("media"), str
        ):
            msg = (
                "rx.island(hydrate=...) media mapping must be exactly "
                '{"media": "<css-media-query>"}.'
            )
            raise CompileError(msg)
        return {"media": hydrate["media"]}
    msg = (
        f"Invalid hydrate={hydrate!r} for rx.island(...). "
        "Expected a strategy string or a media mapping."
    )
    raise CompileError(msg)


class IslandComponent:
    """A thin wrapper recording an explicit island override on a component.

    The wrapper is intentionally not a real :class:`Component` subclass: it
    behaves like a structural marker the Astro page emitter unwraps when
    deciding which `client:*` directive to emit. On the React Router target
    the wrapper is unwrapped during render and the spec is discarded.
    """

    __slots__ = ("component", "spec")

    def __init__(self, component: Component, spec: IslandSpec) -> None:
        """Store the wrapped component and the parsed island spec.

        Args:
            component: The Reflex component to mark as an island root.
            spec: The parsed :class:`IslandSpec` for this override.
        """
        self.component = component
        self.spec = spec

    def render(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate rendering to the wrapped component (React Router fallback).

        Args:
            *args: Positional args forwarded to the wrapped component.
            **kwargs: Keyword args forwarded to the wrapped component.

        Returns:
            The render result of the wrapped component.
        """
        return self.component.render(*args, **kwargs)

    def __repr__(self) -> str:
        """Debug-friendly repr.

        Returns:
            A short `IslandComponent(<inner>, <spec>)` string.
        """
        return f"IslandComponent({self.component!r}, {self.spec!r})"


def island(
    component: Component,
    hydrate: HydrateOption = "load",
    client_only: bool = False,
) -> IslandComponent:
    """Mark a subtree as an explicit client island in `render_mode="islands"`.

    On the Astro target this overrides the compiler's auto-placement to widen
    the boundary, change the hydration strategy, or force `client_only`.

    Compile-time validation:

    - In `render_mode="static"` pages the wrapper is rejected (cannot hydrate).
    - In `render_mode="app"` pages the wrapper is a no-op (whole page is
      already one React root).
    - In `render_mode="islands"` pages the wrapper is honored.
    - Nested `rx.island(...)` is rejected at compile time for v1.

    The mode-specific rejection happens during page compilation, not in this
    factory: a wrapper attached to a component still constructs successfully.

    Args:
        component: The Reflex component to wrap.
        hydrate: Astro hydration strategy: "load" (default, eager), "idle",
            "visible", or a `{"media": "<query>"}` mapping.
        client_only: When True, render with `client:only="react"` (no static
            HTML). Use for browser-only React libraries that cannot run during
            the static build.

    Returns:
        An :class:`IslandComponent` wrapper carrying the parsed spec.

    Raises:
        CompileError: If `hydrate` is not a valid strategy or media mapping,
            or if the wrapped value is itself an `IslandComponent` (nested
            islands are rejected at v1).
    """
    if isinstance(component, IslandComponent):
        msg = (
            "Nested rx.island(...) is rejected in v1. The inner subtree is "
            "already part of the outer island's React tree."
        )
        raise CompileError(msg)
    spec = IslandSpec(hydrate=_validate_hydrate(hydrate), client_only=bool(client_only))
    return IslandComponent(component, spec)
