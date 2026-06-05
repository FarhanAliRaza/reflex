"""Per-component CSS Module support.

A component that subclasses :class:`CSSModuleComponent` declares a co-located
``*.module.css`` file. The compiler copies that stylesheet into the web app and
emits ``import <binding> from "$/styles/components/<id>/<file>.module.css"`` with
a unique binding, but only on pages where the component is actually mounted. The
binding is applied to ``className`` (e.g. ``binding.root``), so unused components
contribute zero CSS — Vite's module graph tree-shakes everything not imported.

Shared "atoms" declared via ``_css_module_shared`` are copied to a single
``styles/_shared`` location so multiple components can ``composes`` from them
without duplicating the rules.
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
from pathlib import Path
from typing import ClassVar

from reflex_base.constants import Dirs
from reflex_base.utils.imports import ImportVar
from reflex_base.vars import VarData
from reflex_base.vars.base import Var

from .component import Component


@dataclasses.dataclass(frozen=True)
class CSSModuleDescriptor:
    """Resolved locations and bindings for a component's CSS module."""

    # Absolute path to the authored ``*.module.css`` source file.
    source_path: Path
    # Path of the copied stylesheet relative to the web dir.
    dest_relpath: str
    # Import specifier used in generated code (``$``-prefixed web path).
    lib: str
    # Unique JS binding for the default import of the module's class map.
    binding: str
    # ``(source_path, dest_relpath)`` pairs for shared atom modules.
    shared: tuple[tuple[Path, str], ...] = ()


def _resolve_relative_to_class(klass: type, raw: str) -> Path:
    """Resolve a CSS module path declared on a class.

    Args:
        klass: The class that declared the path (used to locate its source file).
        raw: The declared path, absolute or relative to the class's source file.

    Returns:
        The resolved absolute path.
    """
    path = Path(raw)
    if not path.is_absolute():
        path = Path(inspect.getfile(klass)).parent / raw
    return path.resolve()


class CSSModuleComponent(Component):
    """A component whose default styling comes from a co-located CSS module."""

    # Path to the component's ``*.module.css``, absolute or relative to the
    # source file of the class that declares it.
    _css_module: ClassVar[str | None] = None

    # The class exported by the module to apply as the root ``className``.
    _css_module_class: ClassVar[str] = "root"

    # Shared atom modules (paths like ``_css_module``) copied once to
    # ``styles/_shared`` for components to ``composes`` from.
    _css_module_shared: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def _css_module_descriptor(cls) -> CSSModuleDescriptor | None:
        """Resolve (and cache) the CSS module locations for this component class.

        Returns:
            The descriptor, or ``None`` if the class declares no CSS module.
        """
        cached = cls.__dict__.get("_css_module_descriptor_cache")
        if cached is not None:
            return cached

        declaring = next(
            (
                klass
                for klass in cls.__mro__
                if klass.__dict__.get("_css_module") is not None
            ),
            None,
        )
        if declaring is None:
            return None

        source_path = _resolve_relative_to_class(declaring, declaring._css_module)
        digest = hashlib.sha1(str(source_path).encode()).hexdigest()[:8]
        dest_relpath = f"{Dirs.STYLES}/components/{digest}/{source_path.name}"

        shared: list[tuple[Path, str]] = []
        for raw in cls._css_module_shared:
            shared_src = _resolve_relative_to_class(declaring, raw)
            shared.append((shared_src, f"{Dirs.STYLES}/_shared/{shared_src.name}"))

        descriptor = CSSModuleDescriptor(
            source_path=source_path,
            dest_relpath=dest_relpath,
            lib=f"$/{dest_relpath}",
            binding=f"_rxcss_{digest}",
            shared=tuple(shared),
        )
        cls._css_module_descriptor_cache = descriptor
        return descriptor

    @classmethod
    def create(cls, *children, **props):
        """Create the component, wiring the CSS module class into ``className``.

        Args:
            *children: The children of the component.
            **props: The props of the component.

        Returns:
            The component instance.
        """
        descriptor = cls._css_module_descriptor()
        if descriptor is not None:
            styles_var = Var(
                _js_expr=f"{descriptor.binding}.{cls._css_module_class}",
                _var_type=str,
                _var_data=VarData(
                    imports={
                        descriptor.lib: [
                            ImportVar(tag=descriptor.binding, is_default=True)
                        ]
                    }
                ),
            )
            user_class_name = props.get("class_name")
            if not user_class_name:
                props["class_name"] = styles_var
            elif isinstance(user_class_name, (list, tuple)):
                props["class_name"] = [styles_var, *user_class_name]
            else:
                props["class_name"] = [styles_var, user_class_name]
        return super().create(*children, **props)

    def _get_css_module_assets(self) -> list[tuple[Path, str]]:
        """Return the stylesheet files this component needs copied into the web dir.

        Returns:
            ``(source_path, web_dest_relpath)`` pairs for the component's module
            and any shared atoms it composes.
        """
        descriptor = type(self)._css_module_descriptor()
        if descriptor is None:
            return []
        return [
            (descriptor.source_path, descriptor.dest_relpath),
            *descriptor.shared,
        ]
