"""Static-mode classifier and rejection for the Astro frontend target.

A page declared as ``@rx.page(render_mode="static")`` must produce 0 KiB of
first-party Reflex runtime JS. The classifier in this module walks a compiled
component tree and yields the offending nodes if anything that requires the
runtime is reached:

- Vars with state-bound ``VarData``,
- ``event_triggers`` (event handlers) on the component,
- components flagged ``requires_hydration``, ``provides_hydrated_context``,
  or ``client_only`` at the class level,
- ``IslandComponent`` wrappers (which presume hydration).

Each finding is returned with file/line metadata where available and routed
through :class:`reflex_base.utils.exceptions.CompileError` by callers in the
compile pipeline.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from reflex_base.utils.exceptions import CompileError

if TYPE_CHECKING:
    from reflex_base.components.component import BaseComponent


@dataclasses.dataclass(frozen=True)
class StaticModeViolation:
    """One offending node found inside a ``render_mode="static"`` page.

    Attributes:
        route: The Reflex route the violation belongs to.
        component_name: The class name of the offending component.
        reason: A short human-readable description of why the node is invalid.
        detail: Optional additional context (e.g. the offending var name).
    """

    route: str
    component_name: str
    reason: str
    detail: str | None = None

    def format(self) -> str:
        """Render the violation as a single error line.

        Returns:
            A formatted string suitable for inclusion in a CompileError msg.
        """
        head = f"  - <{self.component_name}> on route {self.route!r}: {self.reason}"
        if self.detail:
            head = f"{head} ({self.detail})"
        return head


def _component_class_name(component: Any) -> str:
    """Best-effort component class name for diagnostics.

    Args:
        component: The component (or component-like value) being inspected.

    Returns:
        A short identifier for the component class.
    """
    cls = getattr(component, "__class__", None)
    if cls is None:
        return type(component).__name__
    return cls.__name__


def _iter_descendants(component: Any) -> Iterator[Any]:
    """Yield ``component`` and every descendant once.

    Walks ``children`` and unwraps :class:`IslandComponent` so the inner
    component is inspected too. Tolerates non-``BaseComponent`` values
    (strings, Vars, etc.) by skipping them.

    Args:
        component: The root to walk.

    Yields:
        Each visited node in pre-order.
    """
    from reflex_base.components.island import IslandComponent

    stack: list[Any] = [component]
    while stack:
        node = stack.pop()
        if node is None:
            continue
        yield node
        if isinstance(node, IslandComponent):
            stack.append(node.component)
            continue
        children = getattr(node, "children", None)
        if isinstance(children, (list, tuple)):
            stack.extend(children)


def find_static_mode_violations(
    *,
    route: str,
    root: BaseComponent,
) -> list[StaticModeViolation]:
    """Walk a compiled component tree for nodes incompatible with static mode.

    Args:
        route: The Reflex route being inspected; used for error messages.
        root: The root component of the page.

    Returns:
        A list of :class:`StaticModeViolation` instances. Empty when the
        page is safe to emit as static.
    """
    from reflex_base.components.component import Component
    from reflex_base.components.island import IslandComponent

    violations: list[StaticModeViolation] = []

    for node in _iter_descendants(root):
        cls_name = _component_class_name(node)

        if isinstance(node, IslandComponent):
            violations.append(
                StaticModeViolation(
                    route=route,
                    component_name=cls_name,
                    reason="rx.island(...) is not allowed on static pages",
                )
            )
            continue

        if not isinstance(node, Component):
            continue

        if (
            node.client_only
            or node.requires_hydration
            or node.provides_hydrated_context
        ):
            violations.append(
                StaticModeViolation(
                    route=route,
                    component_name=cls_name,
                    reason="component declares hydration metadata",
                    detail=(
                        f"client_only={node.client_only}, "
                        f"requires_hydration={node.requires_hydration}, "
                        f"provides_hydrated_context={node.provides_hydrated_context}"
                    ),
                )
            )
            continue

        # Event triggers anywhere on the page require the runtime.
        if node.event_triggers:
            triggers = ", ".join(sorted(node.event_triggers.keys()))
            violations.append(
                StaticModeViolation(
                    route=route,
                    component_name=cls_name,
                    reason="event triggers are not allowed on static pages",
                    detail=f"triggers={triggers}",
                )
            )
            continue

        # State-bound vars in props/style/class_name/etc.
        for prop_var in node._get_vars(include_children=False):
            var_data = prop_var._get_all_var_data()
            if var_data is not None and getattr(var_data, "state", None):
                violations.append(
                    StaticModeViolation(
                        route=route,
                        component_name=cls_name,
                        reason="state-bound Var is not allowed on static pages",
                        detail=f"state={var_data.state!r}",
                    )
                )
                break

    return violations


def reject_static_mode_violations(
    *,
    route: str,
    root: BaseComponent,
) -> None:
    """Raise CompileError if a static-mode page contains stateful nodes.

    Args:
        route: The Reflex route being inspected; used for error messages.
        root: The root component of the page.

    Raises:
        CompileError: When at least one violation is found. The error
            message lists every offender with component name and reason.
    """
    violations = find_static_mode_violations(route=route, root=root)
    if not violations:
        return
    header = (
        f"render_mode='static' page {route!r} contains nodes that require "
        f"the Reflex runtime. Switch the page to render_mode='app' or "
        f"render_mode='islands', or remove the offending node:"
    )
    lines = [header, *[v.format() for v in violations]]
    raise CompileError("\n".join(lines))
