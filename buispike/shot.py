"""Drive the running spike app with a real browser and capture proof."""

import sys

from playwright.sync_api import expect, sync_playwright

URL = "http://localhost:3000"
OUT = "/tmp"


def run():
    """Render the app, exercise it, and screenshot the results."""
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 900, "height": 700})
        pg.goto(URL, wait_until="networkidle", timeout=60000)

        # Wait for hydration / the card to render.
        expect(pg.get_by_role("heading", name="Base UI + atomic Tailwind")).to_be_visible(
            timeout=30000
        )
        pg.wait_for_timeout(800)
        pg.screenshot(path=f"{OUT}/01_light.png")
        print("light ok")

        # Switch state round-trip: starts "On", click to "Off".
        expect(pg.get_by_text("On", exact=True)).to_be_visible()
        pg.get_by_role("switch").click()
        expect(pg.get_by_text("Off", exact=True)).to_be_visible(timeout=10000)
        print("switch state round-trip ok (On -> Off)")
        pg.get_by_role("switch").click()
        expect(pg.get_by_text("On", exact=True)).to_be_visible(timeout=10000)

        # Dark mode.
        pg.get_by_role("button", name="Toggle theme").click()
        pg.wait_for_timeout(500)
        pg.screenshot(path=f"{OUT}/02_dark.png")
        print("dark ok")

        # Dialog (headless open) — captured in dark to prove portal is themed.
        pg.get_by_role("button", name="Open dialog").click()
        expect(pg.get_by_role("heading", name="Base UI Dialog")).to_be_visible(
            timeout=10000
        )
        pg.wait_for_timeout(400)
        pg.screenshot(path=f"{OUT}/03_dialog_dark.png")
        print("dialog ok")

        # Close via the Base UI close button (focus/escape behavior).
        pg.get_by_role("button", name="Got it").click()
        expect(pg.get_by_role("heading", name="Base UI Dialog")).not_to_be_visible(
            timeout=10000
        )
        print("dialog close ok")
        b.close()
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:  # noqa: BLE001
        print(f"FAILED: {e}")
        sys.exit(1)
