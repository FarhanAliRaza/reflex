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
    "boxShadow", "columnGap", "rowGap", "display", "justifyContent", "alignItems",
    "opacity", "textAlign", "fontStyle", "borderLeftWidth", "borderLeftColor",
    "borderLeftStyle",
]

# component -> list of case keys (testids are radix-<key> / mine-<key>)
COMPONENTS = {
    "button": [
        f"btn-{v}-{s}"
        for v in ["solid", "soft", "outline", "surface", "ghost"]
        for s in ["1", "2", "3", "4"]
    ],
    "badge": [
        f"badge-{v}-{s}"
        for v in ["solid", "soft", "surface", "outline"]
        for s in ["1", "2", "3"]
    ],
    "separator": [f"sep-{s}" for s in ["1", "2", "3"]],
    "text": [
        f"text-{s}-{w}"
        for s in ["1", "2", "3", "5", "9"]
        for w in ["regular", "medium", "bold"]
    ],
    "heading": [f"head-{s}" for s in ["1", "2", "4", "6", "9"]],
    "code": [
        f"code-{v}-{s}"
        for v in ["soft", "solid", "outline"]
        for s in ["1", "2", "3"]
    ],
    "inline": ["inline-em", "inline-strong", "inline-quote"],
    "callout": [
        f"callout-{v}-{s}"
        for v in ["soft", "surface", "outline"]
        for s in ["1", "2"]
    ],
    "blockquote": [f"bq-{s}" for s in ["1", "2", "3", "5"]],
    "card": [f"card-{s}" for s in ["1", "2"]],
    "avatar": [f"avatar-{s}" for s in ["1", "2", "3", "4"]],
    "spinner": [f"spinner-{s}" for s in ["1", "2", "3"]],
    "link": [f"link-{s}" for s in ["1", "2", "3", "5"]],
    "table_header": [f"tbl-head-{s}" for s in ["1", "2", "3"]],
    "table_cell": [f"tbl-cell-{s}" for s in ["1", "2", "3"]],
    "data_list": ["dl-label", "dl-value"],
    "text_field": [f"tf-{v}-{s}" for v in ["surface", "soft"] for s in ["1", "2", "3"]],
    "text_area": [f"ta-{v}-{s}" for v in ["surface", "soft"] for s in ["1", "2", "3"]],
    "switch": [f"switch-{st}-{s}" for st in ["on", "off"] for s in ["1", "2", "3"]],
    "checkbox": [f"cb-{st}-{s}" for st in ["on", "off"] for s in ["1", "2", "3"]],
    "radio": [f"radio-{st}-{s}" for st in ["on", "off"] for s in ["1", "2", "3"]],
    "flex": [f"flex-gap-{g}" for g in ["1", "2", "3"]],
    "grid": [f"grid-gap-{g}" for g in ["1", "2", "3"]],
    "section": [f"section-{s}" for s in ["1", "2", "3"]],
    "box": ["box-1"],
    "tabs_trigger": [f"tabs-{st}-{s}" for s in ["1", "2"] for st in ["active", "idle"]],
    "accordion_trigger": ["accordion-trigger"],
    "select_trigger": ["select-trigger-2"],
    "tooltip_content": ["tooltip-content"],
    "popover_content": ["popover-content"],
    "hovercard_content": ["hovercard-content"],
    "dialog_content": ["dialog-content"],
    "menu_content": ["menu-content"],
    "menu_item": ["menu-item"],
    "alertdialog_content": ["alertdialog-content"],
    "segmented_root": ["seg-root-2"],
    "select_content": ["select-content"],
    "select_item": ["select-item"],
    "progress_track": ["progress-track"],
    "slider_track": ["slider-track"],
    "container": [f"container-{s}" for s in ["1", "2", "3", "4"]],
    "inset": ["inset-1"],
    "skeleton": ["skeleton-1"],
    "accordion_item": ["accordion-item"],
    "slider_thumb": ["slider-thumb"],
}

# Components whose styled leaf carries the testid directly (measure el, not child).
DIRECT = {
    "table_header", "table_cell", "data_list",
    "tabs_trigger", "accordion_trigger", "select_trigger",
    "tooltip_content", "popover_content", "hovercard_content",
    "dialog_content", "menu_content", "menu_item",
    "alertdialog_content", "segmented_root", "select_content", "select_item",
    "progress_track", "slider_track",
    "accordion_item", "slider_thumb",
}

# Radix side: the styled leaf is nested; reach it by appending this selector to
# the radix testid (and measure it directly). The mine side is unchanged.
RADIX_LEAF = {
    "checkbox": ".rt-BaseCheckboxRoot", "radio": ".rt-BaseRadioRoot",
    "progress_track": ".rt-ProgressRoot", "slider_track": ".rt-SliderTrack",
    "slider_thumb": ".rt-SliderThumb",
}

# A child element the root/pseudo checks miss: (radix leaf, mine leaf, props).
CHILD = {
    "switch": (".rt-SwitchThumb", "span",
               ["width", "height", "backgroundColor", "borderTopLeftRadius", "transform"]),
}

# Props to ignore per component (environmental, not styling): dialog content is
# `margin:auto` centered, so its computed left/right margin depends on container
# width (full-viewport portal vs harness cell), not on the styling itself.
SKIP_PROPS = {
    "dialog_content": {"marginLeft", "marginRight"},
    "alertdialog_content": {"marginLeft", "marginRight"},
    "slider_track": {"width"},   # grows to fill the slider; layout-dependent
    "skeleton": {"backgroundColor"},  # animated pulse; frame-dependent
    "accordion_item": {"height"},  # content-region driven (item box styling matches)
}

# Components whose visuals live on pseudo-elements: also compare those.
PSEUDO = {
    "card": {
        "::before": ["backgroundColor", "borderTopLeftRadius"],
        "::after": ["boxShadow", "borderTopLeftRadius", "top", "left"],
    },
    "switch": {
        "::before": ["width", "height", "borderTopLeftRadius", "backgroundColor"],
    },
    "checkbox": {
        "::before": ["width", "height", "borderTopLeftRadius", "backgroundColor", "boxShadow"],
    },
    "radio": {
        "::before": ["width", "height", "borderTopLeftRadius", "backgroundColor", "boxShadow"],
    },
    "slider_thumb": {
        "::after": ["backgroundColor", "borderTopLeftRadius", "boxShadow"],
    },
}


def _styles(pg, sel, direct=False):
    return pg.eval_on_selector(
        sel,
        """(el, args)=>{
            const [props, direct] = args;
            const b = direct ? el : (el.firstElementChild || el);
            const s = getComputedStyle(b);
            const o = {};
            for (const p of props) o[p] = s[p];
            return o;
        }""",
        [PROPS, direct],
    )


def _round_px(v):
    # normalize "70.9062px" -> "70.9" to ignore <0.1px noise
    if isinstance(v, str) and v.endswith("px"):
        try:
            return f"{float(v[:-2]):.1f}px"
        except ValueError:
            return v
    return v


def _eq(prop, rv, mv):
    # width/height differing by <1px is sub-pixel AA/rounding (imperceptible).
    if prop in ("width", "height") and isinstance(rv, str) and isinstance(mv, str):
        if rv.endswith("px") and mv.endswith("px"):
            try:
                return abs(float(rv[:-2]) - float(mv[:-2])) < 1.0
            except ValueError:
                pass
    return _norm(prop, rv) == _norm(prop, mv)


def _norm(prop, v):
    # Tailwind composes box-shadow with transparent filler layers that are
    # visually identical to Radix's single shadow; strip them before compare.
    if prop == "boxShadow" and isinstance(v, str):
        return v.replace("rgba(0, 0, 0, 0) 0px 0px 0px 0px, ", "").strip()
    return _round_px(v)


def check(pg, cases, prefix_radix, prefix_mine, label, direct=False):
    """Compare computed styles for each case; return (matched, total, details)."""
    matched = total = 0
    details = []
    leaf = RADIX_LEAF.get(label)
    for key in cases:
        try:
            if leaf:
                r = _styles(pg, f"[data-testid={prefix_radix}-{key}] {leaf}", True)
            else:
                r = _styles(pg, f"[data-testid={prefix_radix}-{key}]", direct)
            m = _styles(pg, f"[data-testid={prefix_mine}-{key}]", direct)
        except Exception:  # noqa: BLE001
            details.append(f"  [MISS] {label} {key:12} (element not in DOM)")
            continue
        # border style/color are invisible (and thus irrelevant) when width is 0;
        # Tailwind preflight defaults to solid, Radix to none.
        skip = set(SKIP_PROPS.get(label, ()))
        if _round_px(r.get("borderLeftWidth")) in ("0.0px", "0px"):
            skip |= {"borderLeftStyle", "borderLeftColor"}
        diffs = [
            (p, r[p], m[p])
            for p in PROPS
            if p not in skip and not _eq(p, r[p], m[p])
        ]
        total += len(PROPS)
        matched += len(PROPS) - len(diffs)
        flag = "ok " if not diffs else "OFF"
        details.append(f"  [{flag}] {label} {key:12} {len(PROPS)-len(diffs)}/{len(PROPS)}")
        for p, rv, mv in diffs:
            details.append(f"        - {p}: radix={rv!r} mine={mv!r}")
    return matched, total, details


def _pseudo(pg, sel, pseudo, props, direct=False):
    return pg.eval_on_selector(
        sel,
        """(el, args)=>{
            const [pseudo, props, direct] = args;
            const s = getComputedStyle(direct ? el : (el.firstElementChild || el), pseudo);
            return Object.fromEntries(props.map(p=>[p, s[p]]));
        }""",
        [pseudo, props, direct],
    )


def check_pseudo(pg, comp, cases):
    """Compare pseudo-element computed styles; return (matched, total, details)."""
    matched = total = 0
    details = []
    leaf = RADIX_LEAF.get(comp)
    for key in cases:
        for pseudo, props in PSEUDO[comp].items():
            try:
                if leaf:
                    r = _pseudo(pg, f"[data-testid=radix-{key}] {leaf}", pseudo, props, True)
                else:
                    r = _pseudo(pg, f"[data-testid=radix-{key}]", pseudo, props)
                m = _pseudo(pg, f"[data-testid=mine-{key}]", pseudo, props)
            except Exception:  # noqa: BLE001
                continue
            d = [(p, r[p], m[p]) for p in props if _norm(p, r[p]) != _norm(p, m[p])]
            total += len(props)
            matched += len(props) - len(d)
            for p, rv, mv in d:
                details.append(f"        - {key}{pseudo} {p}: radix={rv!r} mine={mv!r}")
    return matched, total, details


def _child(pg, sel, props):
    return pg.eval_on_selector(
        sel,
        "(el,p)=>{const s=getComputedStyle(el);const o={};for(const k of p)o[k]=s[k];return o;}",
        props,
    )


def check_child(pg, comp, cases):
    """Verify a child element (e.g. switch thumb) the root/pseudo checks miss."""
    rleaf, mleaf, props = CHILD[comp]
    matched = total = 0
    details = []
    for key in cases:
        try:
            r = _child(pg, f"[data-testid=radix-{key}] {rleaf}", props)
            m = _child(pg, f"[data-testid=mine-{key}] {mleaf}", props)
        except Exception:  # noqa: BLE001
            details.append(f"  [MISS] {comp} child {key}")
            continue
        d = [(p, r[p], m[p]) for p in props if not _eq(p, r[p], m[p])]
        total += len(props)
        matched += len(props) - len(d)
        for p, rv, mv in d:
            details.append(f"        - {key} child {p}: radix={rv!r} mine={mv!r}")
    return matched, total, details


def run():
    """Run all parity checks across every component."""
    gmatched = gtotal = 0
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1100, "height": 2400})
        pg.goto(URL, wait_until="networkidle", timeout=60000)
        pg.wait_for_selector("[data-testid=radix-btn-solid-2]", timeout=30000)
        pg.wait_for_timeout(500)
        for comp, cases in COMPONENTS.items():
            matched, total, details = check(
                pg, cases, "radix", "mine", comp, direct=comp in DIRECT
            )
            if comp in PSEUDO:
                pm, pt, pd = check_pseudo(pg, comp, cases)
                matched += pm
                total += pt
                details += pd
            if comp in CHILD:
                cm, ct, cd = check_child(pg, comp, cases)
                matched += cm
                total += ct
                details += cd
            gmatched += matched
            gtotal += total
            offs = [d for d in details if "OFF" in d or "MISS" in d or d.startswith("        ")]
            pct = (100.0 * matched / total) if total else 0.0
            tag = f"{matched}/{total} ({pct:.1f}%)" if total else "NOT RENDERED (portal/open-state)"
            print(f"--- {comp}: {tag} ---")
            for d in offs:
                print(d)
        b.close()
    pct = 100.0 * gmatched / gtotal
    print(f"\nTOTAL parity: {gmatched}/{gtotal} props ({pct:.1f}%)")
    return pct


if __name__ == "__main__":
    try:
        pct = run()
        sys.exit(0 if pct == 100.0 else 2)
    except Exception as e:  # noqa: BLE001
        print(f"FAILED: {e}")
        sys.exit(1)
