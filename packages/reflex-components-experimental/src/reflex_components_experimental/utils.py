"""Class-name merging for the experimental components.

``cn`` merges Tailwind class strings via ``clsx-for-tailwind`` (clsx +
tailwind-merge), so a user-supplied ``class_name`` deterministically overrides a
component's defaults (last conflicting utility wins).
"""

from __future__ import annotations

from reflex.utils.imports import ImportVar
from reflex.vars import FunctionVar
from reflex.vars.base import Var, VarData

CN_PACKAGE = "clsx-for-tailwind@1.0.0"

_CN = Var(
    "cn",
    _var_data=VarData(imports={CN_PACKAGE: ImportVar(tag="cn")}),
).to(FunctionVar)


def cn(*classes) -> Var:
    """Merge tailwind class strings/Vars with conflict resolution.

    Args:
        *classes: Class strings or Vars.

    Returns:
        A Var of the merged class string.
    """
    return _CN.call(*classes).to(str)


def merge_class_name(default: str, props: dict) -> None:
    """Set ``props['class_name']`` to ``default`` merged with any user override.

    Without an override the default is kept as a plain string (no runtime
    ``cn()`` call); with one, ``cn`` resolves conflicts at runtime.

    Args:
        default: The component's default class string.
        props: The component props dict (mutated in place).
    """
    user = props.pop("class_name", "")
    props["class_name"] = (
        default if isinstance(user, str) and not user else cn(default, user)
    )
