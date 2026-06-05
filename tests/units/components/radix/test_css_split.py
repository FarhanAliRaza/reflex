"""Tests for splitting the Radix Themes stylesheet into per-component chunks."""

import re
from pathlib import Path

import pytest
from reflex_components_radix.css_split import SHARED_CHUNK, split_radix_css


@pytest.fixture
def components_dir(tmp_path: Path) -> Path:
    """Create a minimal Radix-style ``src/components`` tree.

    Args:
        tmp_path: Pytest temp dir.

    Returns:
        The components directory.
    """
    comp = tmp_path / "components"
    internal = comp / "_internal"
    internal.mkdir(parents=True)
    (internal / "base-button.css").write_text(
        ".rt-BaseButton { display: inline-flex; }"
    )
    (comp / "button.css").write_text(
        "@import './_internal/base-button.css';\n.rt-Button { color: red; }"
    )
    (comp / "icon-button.css").write_text(
        "@import './_internal/base-button.css';\n.rt-IconButton { padding: 0; }"
    )
    (comp / "card.css").write_text(".rt-Card { border: 1px solid; }")
    return comp


# A compiled bundle exercising tokens, a shared base, per-component rules,
# a cross-component rule, a media block spanning components, and keyframes.
COMPILED = """\
:root { --accent: #fff; }
.rt-reset { margin: 0; }
.rt-BaseButton { box-sizing: border-box; }
.rt-Button { color: red; }
.rt-IconButton { padding: 0; }
.rt-Card { border: 1px solid; }
.rt-Button, .rt-Card { font-weight: 500; }
@media (min-width: 768px) {
  .rt-Button { gap: 8px; }
  .rt-Card { gap: 4px; }
  .rt-r-size-2 { font-size: 16px; }
}
@keyframes rt-spin { to { transform: rotate(360deg); } }
"""


def _declarations(css: str) -> set[tuple[str, str]]:
    """Collect ``(context, declaration)`` pairs to compare CSS losslessly.

    Args:
        css: The CSS text.

    Returns:
        Normalized declaration pairs, descending into media blocks.
    """
    pairs: set[tuple[str, str]] = set()

    def walk(text: str, context: str) -> None:
        for rule in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
            prelude = re.sub(r"\s+", " ", rule[0]).strip()
            if prelude.startswith(("@media", "@supports")):
                walk(rule[1], prelude)
                continue
            for decl in rule[1].split(";"):
                normalized = re.sub(r"\s+", " ", decl).strip()
                if normalized:
                    pairs.add((context + "|" + prelude, normalized))

    walk(css, "")
    return pairs


def test_split_is_lossless(components_dir: Path):
    """Every declaration in the bundle survives across the chunks."""
    chunks = split_radix_css(COMPILED, components_dir)
    union = "\n".join(chunks.values())
    assert _declarations(union) == _declarations(COMPILED)


def test_component_rules_land_in_their_chunk(components_dir: Path):
    """A component's own namespace rules go to its chunk, not elsewhere."""
    chunks = split_radix_css(COMPILED, components_dir)
    assert ".rt-Button { color: red; }" in chunks["button"]
    assert ".rt-Card { border: 1px solid; }" not in chunks["button"]
    assert ".rt-Card { border: 1px solid; }" in chunks["card"]


def test_base_namespaces_go_to_shared(components_dir: Path):
    """``rt-Base*`` foundations are shared, not duplicated per component."""
    chunks = split_radix_css(COMPILED, components_dir)
    assert ".rt-BaseButton" in chunks[SHARED_CHUNK]
    assert ".rt-BaseButton" not in chunks["button"]
    assert ".rt-BaseButton" not in chunks["icon-button"]


def test_tokens_and_utilities_go_to_shared(components_dir: Path):
    """Tokens, reset and utility classes belong to the shared base."""
    chunks = split_radix_css(COMPILED, components_dir)
    shared = chunks[SHARED_CHUNK]
    assert "--accent: #fff;" in shared
    assert ".rt-reset" in shared
    assert ".rt-r-size-2" in shared


def test_cross_component_rule_is_duplicated_to_each(components_dir: Path):
    """A rule naming two components appears in both chunks (superset is safe)."""
    chunks = split_radix_css(COMPILED, components_dir)
    assert "font-weight: 500" in chunks["button"]
    assert "font-weight: 500" in chunks["card"]


def test_media_block_is_split_and_rewrapped(components_dir: Path):
    """Responsive variants are distributed per component, keeping the wrapper."""
    chunks = split_radix_css(COMPILED, components_dir)
    assert "@media (min-width: 768px)" in chunks["button"]
    assert "gap: 8px" in chunks["button"]
    assert "gap: 8px" not in chunks["card"]
    # The breakpoint utility class is shared, not component-specific.
    assert "font-size: 16px" in chunks[SHARED_CHUNK]


def test_keyframes_go_to_shared(components_dir: Path):
    """Component-agnostic at-rules stay in the shared base."""
    chunks = split_radix_css(COMPILED, components_dir)
    assert "@keyframes rt-spin" in chunks[SHARED_CHUNK]


def test_missing_components_dir_returns_whole_bundle():
    """With no components directory, the bundle is returned unsplit."""
    chunks = split_radix_css(COMPILED, None)
    assert chunks == {SHARED_CHUNK: COMPILED}


def test_component_stems_restrict_chunks_and_seed_empty(components_dir: Path):
    """Only requested stems get chunks; unrequested owners fall to shared."""
    chunks = split_radix_css(
        COMPILED, components_dir, component_stems=["button", "card"]
    )
    # icon-button was not requested, so it gets no chunk and its rules go shared.
    assert "icon-button" not in chunks
    assert ".rt-IconButton" in chunks[SHARED_CHUNK]
    assert ".rt-IconButton" not in chunks["button"]
    # Requested stems always exist (seeded), even if they own no extra rules.
    assert "button" in chunks
    assert "card" in chunks
    # Still lossless.
    union = "\n".join(chunks.values())
    assert _declarations(union) == _declarations(COMPILED)
