"""Setter-function factory for state vars.

A state var's auto-generated setter (``set_<name>``) is a real Python callable
that mutates state — the event machinery reads its ``__qualname__``,
``__annotations__`` and ``inspect.signature``, so it must be a genuine Python
function (not a builtin closure). ``Var._get_setter`` delegates here so the
factory survives independently of the Var implementation.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from reflex_base import constants
from reflex_base.utils import console


def make_setter(var_type: Any, name: str, js_expr: str) -> Callable[[Any, Any], None]:
    """Build a state var's setter function.

    Args:
        var_type: The var's Python type (numeric types are coerced).
        name: The state attribute name to set.
        js_expr: The var's JS expression (used in the debug message).

    Returns:
        A ``(state, value) -> None`` setter named ``set_<name>``.
    """

    def setter(state: Any, value: Any):
        """Set the var on the state, coercing numeric values.

        Args:
            state: The state instance to mutate.
            value: The value to set.
        """
        if var_type in (int, float):
            try:
                value = var_type(value)
                setattr(state, name, value)
            except ValueError:
                console.debug(
                    f"{type(state).__name__}.{js_expr}: Failed conversion of {value!s} to '{var_type.__name__}'. Value not set.",
                )
        else:
            setattr(state, name, value)

    setter.__annotations__["value"] = var_type
    setter.__qualname__ = constants.SETTER_PREFIX + name

    return setter
