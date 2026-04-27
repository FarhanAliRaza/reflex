"""Base classes + Theme provider for the radix component family.

The Theme provider renders a plain ``<div>`` with the same
``data-accent-color`` / ``data-gray-color`` / ``data-radius`` /
``data-scaling`` / ``data-panel-background`` attributes that
``@radix-ui/themes/tokens.css`` already scopes its CSS variables to
(``[data-accent-color="violet"] { --accent-1: ...; ... }``). That
makes the user's ``rx.theme(accent_color=...)`` config drive the
tokens emitted from ``tokens.css`` without ever loading the full
``@radix-ui/themes/styles.css`` (~800 KB) or the ``@radix-ui/themes``
React package.

``RadixThemesComponent`` is kept as an empty backwards-compat marker
so any third-party package that still inherits from it continues to
import; it no longer sets ``library = "@radix-ui/themes"`` or aliases
its tag.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from reflex_base.components.component import Component, field
from reflex_base.components.tags import Tag
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

LiteralAlign = Literal["start", "center", "end", "baseline", "stretch"]
LiteralJustify = Literal["start", "center", "end", "between"]
LiteralSpacing = Literal["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]
LiteralVariant = Literal["classic", "solid", "soft", "surface", "outline", "ghost"]
LiteralAppearance = Literal["inherit", "light", "dark"]
LiteralGrayColor = Literal["gray", "mauve", "slate", "sage", "olive", "sand", "auto"]
LiteralPanelBackground = Literal["solid", "translucent"]
LiteralRadius = Literal["none", "small", "medium", "large", "full"]
LiteralScaling = Literal["90%", "95%", "100%", "105%", "110%"]
LiteralAccentColor = Literal[
    "tomato", "red", "ruby", "crimson", "pink", "plum", "purple", "violet",
    "iris", "indigo", "blue", "cyan", "teal", "jade", "green", "grass",
    "brown", "orange", "sky", "mint", "lime", "yellow", "amber", "gold",
    "bronze", "gray",
]


_PORTAL_THEME_DEFAULTS: dict[str, str] = {
    "data-accent-color": "indigo",
    "data-gray-color": "auto",
    "data-panel-background": "translucent",
    "data-radius": "medium",
    "data-scaling": "100%",
    "data-has-background": "false",
}

# Populated by Theme.create() so portaled content can mirror the user's
# accent/radius/scaling selections without needing to thread them through
# every Content class. Module-level because ``rx.theme(...)`` is constructed
# at config import time, well before any popover Content runs ``create()``.
_active_theme_attrs: dict[str, str] = {}


def apply_portal_theme(props: dict[str, Any]) -> dict[str, Any]:
    """Mutate ``props`` so a portaled content element re-establishes ``.radix-themes`` scope.

    Adds ``class="radix-themes light"`` and the ``data-*`` attribute values
    that ``tokens.css`` keys variables off, so CSS variables like
    ``--color-panel-solid`` and the user's chosen ``--accent-9`` resolve
    inside portals (which render into ``document.body`` and otherwise miss
    the wrapper's variable scope). Mirrors the
    ``class="radix-themes rt-PopperContent ..."`` pattern the original
    ``@radix-ui/themes`` JS used on every portaled panel.
    """
    custom = dict(props.pop("custom_attrs", {}) or {})
    for key, default in _PORTAL_THEME_DEFAULTS.items():
        custom.setdefault(key, _active_theme_attrs.get(key, default))
    existing = props.pop("class_name", "")
    props["class_name"] = f"radix-themes light {existing}".strip()
    props["custom_attrs"] = custom
    return props


class CommonMarginProps(Component):
    """Common shorthand margin props."""

    m: Var[LiteralSpacing] = field(doc='Margin: "0" - "9" # noqa: ERA001')
    mx: Var[LiteralSpacing] = field(doc='Margin horizontal: "0" - "9"')
    my: Var[LiteralSpacing] = field(doc='Margin vertical: "0" - "9"')
    mt: Var[LiteralSpacing] = field(doc='Margin top: "0" - "9"')
    mr: Var[LiteralSpacing] = field(doc='Margin right: "0" - "9"')
    mb: Var[LiteralSpacing] = field(doc='Margin bottom: "0" - "9"')
    ml: Var[LiteralSpacing] = field(doc='Margin left: "0" - "9"')


class CommonPaddingProps(Component):
    """Common shorthand padding props."""

    p: Var[Responsive[LiteralSpacing]] = field(doc='Padding: "0" - "9" # noqa: ERA001')
    px: Var[Responsive[LiteralSpacing]] = field(doc='Padding horizontal: "0" - "9"')
    py: Var[Responsive[LiteralSpacing]] = field(doc='Padding vertical: "0" - "9"')
    pt: Var[Responsive[LiteralSpacing]] = field(doc='Padding top: "0" - "9"')
    pr: Var[Responsive[LiteralSpacing]] = field(doc='Padding right: "0" - "9"')
    pb: Var[Responsive[LiteralSpacing]] = field(doc='Padding bottom: "0" - "9"')
    pl: Var[Responsive[LiteralSpacing]] = field(doc='Padding left: "0" - "9"')


class RadixLoadingProp(Component):
    """Mixin for components with a ``loading`` prop."""

    loading: Var[bool] = field(
        doc="If set, show an rx.spinner instead of the component children."
    )


class RadixThemesComponent(Component):
    """Backwards-compat marker — no longer pulls in @radix-ui/themes.

    Prior versions of ``reflex-components-radix`` set
    ``library = "@radix-ui/themes@3.3.0"`` on this class so every
    component compiled with a JSX import for the heavyweight
    ``@radix-ui/themes`` package. Components in this package now render
    plain HTML / @radix-ui/react-* primitives with Tailwind utility
    classes, and the ``Theme`` provider below emits the same
    ``data-accent-color`` etc. attributes that ``tokens.css`` scopes
    its CSS variables to. The class is kept (empty) because external
    packages still subclass it.
    """

    @staticmethod
    def _get_app_wrap_components() -> dict[tuple[int, str], Component]:
        return {
            (45, "RadixThemesColorModeProvider"): RadixThemesColorModeProvider.create(),
        }


class RadixThemesTriggerComponent(RadixThemesComponent):
    """Backwards-compat alias for the trigger pattern."""

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a trigger component.

        Args:
            *children: Children of the trigger.
            **props: Props of the trigger.

        Returns:
            The trigger component (children with on_click are wrapped
            in a Flex so the parent's on_click stays bound).
        """
        from .layout.flex import Flex

        for child in children:
            if "on_click" in getattr(child, "event_triggers", {}):
                children = (Flex.create(*children),)
                break
        return super().create(*children, **props)


class Theme(elements.Div):
    """Theme provider — emits ``data-*`` attributes ``tokens.css`` keys off.

    The ``rx.theme(...)`` call places this wrapper at the root of the
    app. The data attributes (``data-accent-color`` etc.) are exactly
    what ``@radix-ui/themes/tokens.css`` scopes its variable
    declarations to, so the user's chosen colors / radius / scaling
    drive every component on the page without any of the original
    ``@radix-ui/themes`` JS or component CSS being loaded.
    """

    tag = "div"

    has_background: Var[bool] = field(doc="Apply theme background to root")
    appearance: Var[LiteralAppearance] = field(
        doc='Override light/dark: "inherit" | "light" | "dark"'
    )
    accent_color: Var[LiteralAccentColor] = field(doc="Accent color scale")
    gray_color: Var[LiteralGrayColor] = field(doc="Gray scale")
    panel_background: Var[LiteralPanelBackground] = field(doc="Panel background")
    radius: Var[LiteralRadius] = field(doc="Element border radius")
    scaling: Var[LiteralScaling] = field(doc="Scale of all theme items")

    @classmethod
    def create(
        cls,
        *children: Any,
        color_mode: LiteralAppearance | None = None,
        theme_panel: bool = False,
        **props: Any,
    ) -> Component:
        """Create a Theme provider wrapper.

        Args:
            *children: Page children.
            color_mode: Mapped onto ``appearance`` for back-compat.
            theme_panel: Ignored — the visual editor is no longer shipped.
            **props: ``accent_color``, ``gray_color``, ``radius`` etc.

        Returns:
            A ``<div>`` with ``data-*`` attributes that the
            ``tokens.css`` selectors key off, so the user's chosen
            colors / radius / scaling drive every component on the
            page.
        """
        if color_mode is not None:
            props["appearance"] = color_mode
        # Don't reify Theme Panel anymore — we no longer ship a JS visual editor.
        _ = theme_panel

        # Drop the data-* attributes through custom_attrs so the JSX
        # renderer emits them as quoted string keys (raw kebab keys
        # would otherwise produce invalid JS object literals).
        custom = dict(props.pop("custom_attrs", {}) or {})
        for prop_name, attr_name, default in (
            ("accent_color", "data-accent-color", "indigo"),
            ("gray_color", "data-gray-color", "auto"),
            ("panel_background", "data-panel-background", "translucent"),
            ("radius", "data-radius", "medium"),
            ("scaling", "data-scaling", "100%"),
            ("has_background", "data-has-background", "true"),
        ):
            if prop_name in props:
                custom[attr_name] = props.pop(prop_name)
            else:
                custom.setdefault(attr_name, default)
        custom.setdefault("data-is-root-theme", "true")
        # Stash the resolved data-* attrs for ``apply_portal_theme`` to mirror
        # onto each portaled content panel. Captures the most recent
        # ``rx.theme(...)`` call's attrs.
        _active_theme_attrs.clear()
        for k, v in custom.items():
            if isinstance(v, str):
                _active_theme_attrs[k] = v

        existing = props.pop("class_name", "")
        # Default class so user theme overrides via .radix-themes selector keep working.
        class_name = f"radix-themes {existing}".strip()
        # Mirror appearance onto the class name so tokens.css' `.light` /
        # `.dark` selectors fire too.
        appearance = props.get("appearance")
        if appearance in ("light", "dark"):
            class_name = f"{class_name} {appearance}".strip()

        props["class_name"] = class_name
        props["custom_attrs"] = custom
        return super().create(*children, **props)

    def _render(self, props: dict[str, Any] | None = None) -> Tag:
        tag = super()._render(props)
        return tag.remove_props("appearance")


class ThemePanel(elements.Div):
    """Theme-editor panel — kept as a no-op for back-compat.

    The original Radix Themes ThemePanel was a visual editor that lived
    inside the @radix-ui/themes JS bundle. With that package gone, the
    panel becomes a no-op (renders an empty div). Apps that need the
    full editor should import @radix-ui/themes themselves and use it
    directly.
    """

    tag = "div"

    default_open: Var[bool] = field(doc="(no-op — kept for back-compat)")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a no-op theme-panel placeholder.

        Args:
            *children: Ignored.
            **props: Ignored.

        Returns:
            A hidden div.
        """
        return super().create(class_name="hidden")


class RadixThemesColorModeProvider(Component):
    """React-themes integration for radix themes components."""

    library = "$/components/reflex/radix_themes_color_mode_provider"
    tag = "RadixThemesColorModeProvider"
    is_default = True


theme = Theme.create
theme_panel = ThemePanel.create
