"""Plugin support for opt-in Radix Themes integration."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING, Any

from reflex_base.components.component import BaseComponent, Component
from reflex_base.components.dynamic import bundle_library
from reflex_base.constants.base import Dirs, Javascript
from reflex_base.plugins.base import Plugin
from reflex_base.utils import console

from reflex_components_radix import themes
from reflex_components_radix.css_split import (
    ACCENT_COLORS,
    radix_chunk_name,
    split_radix_css,
)
from reflex_components_radix.themes.base import RadixThemesComponent

if TYPE_CHECKING:
    from reflex_base.plugins.compiler import PageContext


def _all_radix_subclasses() -> set[type[RadixThemesComponent]]:
    """Collect every loaded Radix Themes component class.

    Returns:
        All transitive subclasses of :class:`RadixThemesComponent`. Any
        component used in the app is imported, so its chunk is generated.
    """
    seen: set[type[RadixThemesComponent]] = set()
    stack = [RadixThemesComponent]
    while stack:
        cls = stack.pop()
        for sub in cls.__subclasses__():
            if sub not in seen:
                seen.add(sub)
                stack.append(sub)
    return seen


RADIX_THEMES_STYLESHEET = "@radix-ui/themes/styles.css"
RADIX_THEMES_PACKAGE = "@radix-ui/themes@3.3.0"
# Per-component CSS chunks are written here, under .web/styles.
RADIX_CSS_DIR = "radix"
# Marks a component instance whose CSS should be imported per-component.
RADIX_CSS_SPLIT_ATTR = "_radix_css_split"
_DEPRECATION_VERSION = "0.9.0"
_REMOVAL_VERSION = "1.0"


@dataclasses.dataclass
class RadixThemesPlugin(Plugin):
    """Opt-in plugin for Radix Themes assets and app-level wrapping."""

    theme: Component | None = dataclasses.field(
        default_factory=lambda: themes.theme(accent_color="blue")
    )
    enabled: bool = dataclasses.field(default=True, repr=False)
    # Opt in to per-component CSS: replace the monolithic Radix Themes bundle
    # with a shared base plus per-component chunks, so pages only load the CSS
    # for components they actually render. Pixel-identical to the full bundle.
    css_splitting: bool = False
    _explicit: bool = dataclasses.field(default=True, repr=False)
    _app_theme_warning_emitted: bool = dataclasses.field(
        default=False, init=False, repr=False
    )

    @classmethod
    def create_implicit(cls) -> RadixThemesPlugin:
        """Create a compile-local plugin that starts disabled.

        Returns:
            The disabled compile-local plugin.
        """
        return cls(enabled=False, _explicit=False)

    def get_stylesheet_paths(self, **context: Any) -> tuple[str, ...]:
        """Return the Radix Themes stylesheet when enabled.

        With per-component CSS splitting on, the monolithic bundle is replaced by
        the shared base plus per-component chunks imported by the components
        themselves, so it is not injected globally here.
        """
        if not self.enabled or self.css_splitting:
            return ()
        return (RADIX_THEMES_STYLESHEET,)

    def get_frontend_dependencies(self, **context: Any) -> tuple[str, ...]:
        """Return the Radix Themes package when enabled."""
        return (RADIX_THEMES_PACKAGE,) if self.enabled else ()

    def get_static_assets(self, **context: Any) -> list[tuple[Path, str | bytes]]:
        """Emit the split Radix Themes CSS chunks when splitting is enabled.

        Reads the installed ``@radix-ui/themes`` bundle and splits it into a
        shared base plus one chunk per component, written under
        ``.web/styles/radix``. Returns nothing (loading the full bundle instead)
        when splitting is off or the package is not yet installed.

        Returns:
            ``(path, content)`` pairs for each chunk, relative to the web dir.
        """
        if not (self.enabled and self.css_splitting):
            return []

        from reflex.utils.prerequisites import get_web_dir

        package = get_web_dir() / Javascript.NODE_MODULES / "@radix-ui" / "themes"
        bundle = package / "styles.css"
        if not bundle.is_file():
            return []

        components_dir = package / "src" / "components"
        stems = {
            radix_chunk_name(tag)
            for cls in _all_radix_subclasses()
            if isinstance(tag := getattr(cls, "tag", None), str) and tag
        }
        chunks = split_radix_css(
            bundle.read_text(encoding="utf-8"),
            components_dir,
            stems,
            accent_colors=ACCENT_COLORS,
        )
        base = Path(Dirs.STYLES) / RADIX_CSS_DIR
        return [(base / f"{name}.css", css) for name, css in chunks.items()]

    def enter_component(
        self,
        comp: BaseComponent,
        /,
        *,
        page_context: PageContext,
        compile_context: Any,
        in_prop_tree: bool = False,
    ) -> None:
        """Auto-enable the plugin when a Radix Themes component is compiled."""
        if not isinstance(comp, RadixThemesComponent):
            return

        # Mark every Radix component so it imports its own CSS chunk. Done before
        # imports are gathered, while walking the component tree.
        if self.css_splitting:
            setattr(comp, RADIX_CSS_SPLIT_ATTR, True)

        if self.enabled:
            return

        self.enabled = True
        bundle_library(RADIX_THEMES_PACKAGE)
        if not self._explicit and not self._app_theme_warning_emitted:
            console.deprecate(
                feature_name="Implicit Radix Themes enablement",
                reason=(
                    "a Radix Themes component was detected, which enables the full "
                    "Radix CSS bundle. Configure `rx.plugins.RadixThemesPlugin()` in "
                    "`rxconfig.py` to make this explicit, or remove Radix components "
                    "to avoid loading the stylesheet"
                ),
                deprecation_version=_DEPRECATION_VERSION,
                removal_version=_REMOVAL_VERSION,
            )

    def compile_page(
        self,
        page_ctx: PageContext,
        /,
        **kwargs: Any,
    ) -> None:
        """Inject the app-level theme wrapper when Radix Themes is active."""
        if self.enabled and self.theme is not None:
            # The app-wrap theme is not walked by enter_component, so mark it here
            # to ensure it imports the shared base and the default accent chunk.
            if self.css_splitting:
                setattr(self.theme, RADIX_CSS_SPLIT_ATTR, True)
            page_ctx.app_wrap_components[20, "Theme"] = self.theme

    def get_theme(self) -> Component | None:
        """Return the effective theme component for the active compile."""
        return self.theme if self.enabled else None

    def apply_app_theme(self, theme: Component) -> None:
        """Handle deprecated ``App(theme=...)`` compatibility."""
        console.deprecate(
            feature_name="App(theme=...)",
            reason=(
                "configure `rx.plugins.RadixThemesPlugin(theme=...)` in "
                "`rxconfig.py` instead"
            ),
            deprecation_version=_DEPRECATION_VERSION,
            removal_version=_REMOVAL_VERSION,
        )
        self._app_theme_warning_emitted = True

        if self._explicit:
            return

        self.enabled = True
        self.theme = theme
