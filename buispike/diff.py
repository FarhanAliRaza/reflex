"""Computed-style parity check: every parity component vs its Radix reference.

Pixel-diffing two *different* implementations is dominated by anti-aliasing
noise from sub-pixel screen positions, so the rigorous oracle is computed-style
equality: if the rendered box model + typography + color + borders match, the
components are visually identical by construction. We compare a rich property
set for each case and report mismatches.
"""

import sys

from playwright.sync_api import sync_playwright

URL = "http://localhost:3000"

PROPS = [
    "width", "height",
    "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
    "marginTop", "marginRight", "marginBottom", "marginLeft",
    "fontSize", "fontWeight", "fontFamily", "letterSpacing", "lineHeight",
    "color", "backgroundColor",
    "borderTopLeftRadius", "borderTopRightRadius",
    "borderBottomLeftRadius", "borderBottomRightRadius",
    "boxShadow", "columnGap", "display", "justifyContent", "alignItems",
    "opacity", "textAlign",
]

# (key prefix, list of case keys) per component
BUTTON_CASES = [
    f"{v}-{s}"
    for v in ["solid", "soft", "outline", "surface", "ghost"]
    for s in ["1", "2", "3", "4"]
]


def _styles(pg, sel):
    return pg.eval_on_selector(
        sel,
        """(el, props)=>{
            const b = el.tagName==='BUTTON' ? el : (el.querySelector('button,input,[role=switch]')||el);
            const s = getComputedStyle(b);
            const o = {};
            for (const p of props) o[p] = s[p];
            return o;
        }""",
        PROPS,
    )


def _round_px(v):
    # normalize "70.9062px" -> "70.9" to ignore <0.1px noise
    if isinstance(v, str) and v.endswith("px"):
        try:
            return f"{float(v[:-2]):.1f}px"
        except ValueError:
            return v
    return v


def _norm(prop, v):
    # Tailwind composes box-shadow with transparent filler layers that are
    # visually identical to Radix's single shadow; strip them before compare.
    if prop == "boxShadow" and isinstance(v, str):
        layers = [s.strip() for s in v.split(",")]
        layers = [s for s in layers if not s.startswith("rgba(0, 0, 0, 0) 0px 0px 0px 0px")]
        return ", ".join(layers)
    return _round_px(v)


def check(pg, cases, prefix_radix, prefix_mine, label):
    """Compare computed styles for each case; return (matched, total, details)."""
    matched = total = 0
    details = []
    for key in cases:
        r = _styles(pg, f"[data-testid={prefix_radix}-{key}]")
        m = _styles(pg, f"[data-testid={prefix_mine}-{key}]")
        diffs = [
            (p, r[p], m[p])
            for p in PROPS
            if _norm(p, r[p]) != _norm(p, m[p])
        ]
        total += len(PROPS)
        matched += len(PROPS) - len(diffs)
        flag = "ok " if not diffs else "OFF"
        details.append(f"  [{flag}] {label} {key:12} {len(PROPS)-len(diffs)}/{len(PROPS)}")
        for p, rv, mv in diffs:
            details.append(f"        - {p}: radix={rv!r} mine={mv!r}")
    return matched, total, details


def run():
    """Run all parity checks."""
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1100, "height": 1600})
        pg.goto(URL, wait_until="networkidle", timeout=60000)
        pg.wait_for_selector("[data-testid=radix-solid-2]", timeout=30000)
        pg.wait_for_timeout(500)
        matched, total, details = check(pg, BUTTON_CASES, "radix", "mine", "button")
        b.close()
    print("\n".join(details))
    pct = 100.0 * matched / total
    print(f"\nButton parity: {matched}/{total} props ({pct:.1f}%)")
    return pct


if __name__ == "__main__":
    try:
        pct = run()
        sys.exit(0 if pct == 100.0 else 2)
    except Exception as e:  # noqa: BLE001
        print(f"FAILED: {e}")
        sys.exit(1)
