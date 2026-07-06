"""Vendor Radix color scales into the package as per-color CSS data files.

For each color, concatenates the four ``@radix-ui/colors`` files (light, dark,
alpha, dark-alpha — each with their Display-P3 blocks) with the
``@radix-ui/themes`` per-color specials (``--<color>-contrast/surface/
indicator/track``) into ``src/reflex_components_experimental/radix_colors/
<color>.css``. ``ExperimentalThemePlugin`` assembles the theme stylesheet from
these at compile time, shipping only the chosen accent + gray scales.

Re-run when bumping the vendored @radix-ui/themes version:

    uv run python scripts/vendor_radix_colors.py <path-to-node_modules>
"""

import re
import sys
from pathlib import Path

PKG_DIR = Path(__file__).parent.parent / "src" / "reflex_components_experimental"
OUT_DIR = PKG_DIR / "radix_colors"


def vendor(node_modules: Path) -> None:
    """Extract every Radix color scale into the package data directory.

    Args:
        node_modules: A node_modules directory containing ``@radix-ui/colors``
            and ``@radix-ui/themes``.

    Raises:
        FileNotFoundError: If the Radix packages are not present.
    """
    colors_dir = node_modules / "@radix-ui" / "colors"
    themes_colors_dir = (
        node_modules / "@radix-ui" / "themes" / "src" / "styles" / "tokens" / "colors"
    )
    if not colors_dir.is_dir() or not themes_colors_dir.is_dir():
        msg = f"@radix-ui/colors + @radix-ui/themes not found under {node_modules}"
        raise FileNotFoundError(msg)

    version = re.search(
        r'"version":\s*"([^"]+)"',
        (node_modules / "@radix-ui" / "themes" / "package.json").read_text(),
    )
    header = (
        f"/* Vendored from @radix-ui/colors + @radix-ui/themes"
        f"{'@' + version.group(1) if version else ''} (MIT)."
        " Regenerate with scripts/vendor_radix_colors.py. */\n"
    )

    OUT_DIR.mkdir(exist_ok=True)
    for themes_css in sorted(themes_colors_dir.glob("*.css")):
        color = themes_css.stem
        parts = [header]
        parts.extend(
            (colors_dir / f"{color}{suffix}.css").read_text().strip()
            for suffix in ("", "-dark", "-alpha", "-dark-alpha")
        )
        # themes specials (contrast/surface/indicator/track), sans the imports
        specials = re.sub(
            r"^@import [^\n]+\n", "", themes_css.read_text(), flags=re.MULTILINE
        )
        parts.append(specials.strip())
        (OUT_DIR / f"{color}.css").write_text("\n\n".join(parts) + "\n")
        print(f"vendored {color}")


if __name__ == "__main__":
    vendor(Path(sys.argv[1]))
