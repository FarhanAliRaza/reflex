"""Plugin that ships the experimental design-token theme + its frontend deps.

The theme stylesheet is generated at compile time from vendored Radix color
data (``radix_colors/``): only the chosen accent + gray scales are emitted,
with ``--accent-*`` / ``--gray-*`` aliased to them, mirroring how Radix Themes
maps ``accentColor`` / ``grayColor``. Enable in ``rxconfig.py`` alongside
``TailwindV4Plugin`` (the components are authored as Tailwind utilities):

    config = rx.Config(
        app_name="myapp",
        plugins=[
            rx.plugins.TailwindV4Plugin(),
            ExperimentalThemePlugin(accent_color="iris", gray_color="sand"),
        ],
    )
"""

from __future__ import annotations

import dataclasses
import importlib.resources
from pathlib import Path
from typing import Any

from reflex_base.constants import Dirs
from reflex_base.plugins.base import Plugin

from reflex_components_experimental.utils import CN_PACKAGE

THEME_FILENAME = "experimental-theme.css"

GRAY_COLORS = frozenset({"gray", "mauve", "slate", "sage", "olive", "sand"})
ACCENT_COLORS = frozenset({
    "amber",
    "blue",
    "bronze",
    "brown",
    "crimson",
    "cyan",
    "gold",
    "grass",
    "gray",
    "green",
    "indigo",
    "iris",
    "jade",
    "lime",
    "mint",
    "orange",
    "pink",
    "plum",
    "purple",
    "red",
    "ruby",
    "sky",
    "teal",
    "tomato",
    "violet",
    "yellow",
})
# radius -> (--radius-factor, --radius-full, --radius-thumb), per Radix.
RADIUS_TOKENS = {
    "none": ("0", "0px", "0.5px"),
    "small": ("0.75", "0px", "0.5px"),
    "medium": ("1", "0px", "9999px"),
    "large": ("1.5", "0px", "9999px"),
    "full": ("1.5", "9999px", "9999px"),
}
SCALING_FACTORS = {
    "90%": "0.9",
    "95%": "0.95",
    "100%": "1",
    "105%": "1.05",
    "110%": "1.1",
}

_ALIAS_TOKENS = [*(str(n) for n in range(1, 13)), *(f"a{n}" for n in range(1, 13))]
_SPECIAL_TOKENS = ["contrast", "surface", "indicator", "track"]


def _data(name: str) -> str:
    """Read a packaged CSS data file.

    Args:
        name: Path of the file relative to the package root.

    Returns:
        The file contents.
    """
    return (
        importlib.resources.files("reflex_components_experimental") / name
    ).read_text(encoding="utf-8")


def _aliases(semantic: str, scale: str) -> list[str]:
    """Alias a semantic token family onto a color scale.

    Args:
        semantic: The semantic family name (e.g. ``"accent"``).
        scale: The backing scale name (e.g. ``"iris"``).

    Returns:
        ``--<semantic>-*: var(--<scale>-*)`` declaration lines.
    """
    return [
        f"  --{semantic}-{t}: var(--{scale}-{t});"
        for t in (*_ALIAS_TOKENS, *_SPECIAL_TOKENS)
    ]


def _validate(field: str, value: str, valid: frozenset[str] | dict[str, Any]) -> None:
    """Raise for a theme option outside its valid set.

    Args:
        field: The option name (for the error message).
        value: The supplied value.
        valid: The allowed values.

    Raises:
        ValueError: If ``value`` is not allowed.
    """
    if value not in valid:
        msg = f"Invalid {field} {value!r}; expected one of {sorted(valid)}."
        raise ValueError(msg)


@dataclasses.dataclass
class ExperimentalThemePlugin(Plugin):
    """Generates the Radix-token theme stylesheet and ships the ``cn`` dependency.

    The options mirror ``rx.theme``: ``accent_color``/``gray_color`` pick the
    Radix scales the semantic ``--accent-*``/``--gray-*`` tokens resolve to,
    ``radius`` sets the corner-radius factor, and ``scaling`` the global size
    multiplier. Light, dark and Display-P3 variants of the chosen scales are
    all included; nothing else ships.
    """

    accent_color: str = "violet"
    gray_color: str = "slate"
    radius: str = "medium"
    scaling: str = "100%"

    def __post_init__(self):
        """Validate the theme options.

        Raises:
            ValueError: If any option is outside its valid set.
        """
        _validate("accent_color", self.accent_color, ACCENT_COLORS)
        _validate("gray_color", self.gray_color, GRAY_COLORS)
        _validate("radius", self.radius, RADIUS_TOKENS)
        _validate("scaling", self.scaling, SCALING_FACTORS)

    def _theme_css(self) -> str:
        """Assemble the theme stylesheet for the configured options.

        Returns:
            The chosen color scales, the base tokens, and the semantic
            alias/factor overrides, in cascade order.
        """
        # A "gray" accent follows the chosen gray scale, like Radix.
        accent = self.gray_color if self.accent_color == "gray" else self.accent_color
        scales = dict.fromkeys((self.gray_color, accent))
        factor, full, thumb = RADIUS_TOKENS[self.radius]
        overrides = [
            ":root, .light {",
            *_aliases("accent", accent),
            *_aliases("primary", accent),
            *_aliases("secondary", self.gray_color),
            # --gray-* IS the scale when gray_color="gray"; aliasing would cycle.
            *(_aliases("gray", self.gray_color) if self.gray_color != "gray" else []),
            f"  --scaling: {SCALING_FACTORS[self.scaling]};",
            f"  --radius-factor: {factor};",
            f"  --radius-full: {full};",
            f"  --radius-thumb: {thumb};",
            "}",
        ]
        return "\n\n".join([
            *(_data(f"radix_colors/{scale}.css") for scale in scales),
            _data("theme.css"),
            "\n".join(overrides),
        ])

    def get_static_assets(self, **context: Any) -> list[tuple[Path, str]]:
        """Write the generated token theme into the web styles directory.

        Returns:
            A single ``(dest_path, css)`` pair under ``styles/``.
        """
        return [(Path(Dirs.STYLES) / THEME_FILENAME, self._theme_css())]

    def get_stylesheet_paths(self, **context: Any) -> tuple[str, ...]:
        """Reference the token theme from the root stylesheet.

        Returns:
            The theme stylesheet path relative to the styles directory.
        """
        return (f"./{THEME_FILENAME}",)

    def get_frontend_dependencies(self, **context: Any) -> tuple[str, ...]:
        """Declare the npm package backing ``cn`` (clsx + tailwind-merge).

        Returns:
            The ``clsx-for-tailwind`` package spec.
        """
        return (CN_PACKAGE,)
