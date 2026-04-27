"""Capture screenshots of the running visual-diff harness.

Assumes ``reflex run`` is already serving the harness on
``http://localhost:3000``. Saves a full-page PNG to
``screenshots/buttons.png`` and a per-row crop for each size to
``screenshots/buttons-size-<n>.png`` so a reviewer can compare the
exact pixel rectangles for each Radix vs shadcn variant pair.

Usage::

    cd examples/visual_diff_buttons
    uv run reflex run &
    uv run python capture.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://localhost:3000"
OUT_DIR = Path(__file__).parent / "screenshots"


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 2400})
        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector("button", timeout=10_000)
        page.screenshot(path=str(OUT_DIR / "buttons.png"), full_page=True)
        for size_idx in range(4):
            heading = page.locator("h2").nth(size_idx)
            row = heading.locator("xpath=..")
            row.screenshot(path=str(OUT_DIR / f"buttons-size-{size_idx + 1}.png"))
        browser.close()
    print(f"Wrote screenshots to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
