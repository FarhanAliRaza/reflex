"""Class-name merging for the experimental components.

``cn`` merges Tailwind class strings via ``clsx-for-tailwind`` (clsx +
tailwind-merge), so a user-supplied ``class_name`` deterministically overrides a
component's defaults (last conflicting utility wins).
"""

from __future__ import annotations

from collections.abc import Callable

from reflex_components_core.core.match import match

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


def merge_class_name(default: str | Var, props: dict) -> None:
    """Set ``props['class_name']`` to ``default`` merged with any user override.

    Without an override the default is kept as-is (no runtime ``cn()`` call);
    with one, ``cn`` resolves conflicts at runtime.

    Args:
        default: The component's default class string (or class Var).
        props: The component props dict (mutated in place).
    """
    user = props.pop("class_name", "")
    props["class_name"] = (
        default if isinstance(user, str) and not user else cn(default, user)
    )


def variant_classes(
    build: Callable[..., str],
    dims: dict[str, tuple[str | Var, tuple[str, ...], str]],
) -> str | Var:
    """Resolve size/variant-style props that may be state ``Var``s.

    Static values resolve directly to ``build``'s class string. For each
    ``Var`` dimension, every valid value is enumerated into an ``rx.match``
    branch, so all class strings stay compile-time literals in the emitted JS
    — which is what keeps them visible to the Tailwind scanner. A runtime
    value outside the valid set falls back to the dimension's default.

    Args:
        build: Maps concrete dimension values (as keyword args) to a class
            string.
        dims: ``name -> (value, valid values, default value)`` per dimension.

    Returns:
        A plain class string when every dimension is static, otherwise a
        match Var enumerating the dynamic combinations.
    """
    names = list(dims)

    def resolve(bound: dict[str, str], remaining: list[str]) -> str | Var:
        if not remaining:
            return build(**bound)
        name, *rest = remaining
        value, domain, default = dims[name]
        if not isinstance(value, Var):
            return resolve({**bound, name: value}, rest)
        return match(  # pyright: ignore[reportReturnType] (non-component cases produce a Var)
            value,
            *((v, resolve({**bound, name: v}, rest)) for v in domain),
            resolve({**bound, name: default}, rest),
        )

    return resolve({}, names)
