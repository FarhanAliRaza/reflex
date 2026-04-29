"""Integration tests for auto-memoization edge cases.

These exercise components whose memoization needs special care:

- Snapshot boundaries (``recursive=False``) such as ``AccordionTrigger`` whose
  state-dependent logic lives in a descendant. Without the snapshot wrapper
  the cond's state read leaks into the page module and the trigger fails to
  update on state transitions.
- HTML elements with constrained content models (``<title>``, ``<meta>``,
  ``<style>``, ``<script>``). Independent memoization of a stateful ``Bare``
  child renders ``jsx("title", {}, jsx(Bare_xxx, {}))`` — React stringifies
  the component child as ``[object Object]`` (or refuses to render at all
  for void elements). Snapshot-wrapping keeps the Bare a text interpolation
  inside the parent's body.

Test design notes:
- ``document.title`` is not a reliable signal: React Router writes a
  metadata title alongside any user-rendered ``<title>``. Tests inspect the
  ``<title>`` element directly rather than ``document.title``.
- Style content is matched on a unique marker substring rather than common
  selectors like ``body`` (which conflicts with Emotion/Sonner stylesheets).
- ``<textarea>``'s runtime value semantics belong to React (children are
  initial-value-only); the no-Bare-component-child invariant is verified by
  the unit tests instead.
"""

from collections.abc import Generator

import pytest
from playwright.sync_api import Page, expect

from reflex.testing import AppHarness


def MemoEdgeCasesApp():
    """App exercising memoization edge cases."""
    import reflex as rx

    class MemoState(rx.State):
        is_open: bool = False
        title_marker: str = "memo-title-home"
        css_marker: str = "memo-css-light"
        counter: int = 0

        @rx.event
        def toggle_open(self):
            self.is_open = not self.is_open

        @rx.event
        def set_title_about(self):
            self.title_marker = "memo-title-about"

        @rx.event
        def set_css_dark(self):
            self.css_marker = "memo-css-dark"

        @rx.event
        def bump(self):
            self.counter = self.counter + 1

    def index():
        return rx.box(
            rx.el.title(MemoState.title_marker),
            rx.el.style("body { --memo-marker: " + MemoState.css_marker + "; }"),
            rx.box(
                rx.button("toggle", on_click=MemoState.toggle_open, id="toggle"),
                rx.button("title", on_click=MemoState.set_title_about, id="set-title"),
                rx.button("css", on_click=MemoState.set_css_dark, id="set-css"),
                rx.button("bump", on_click=MemoState.bump, id="bump"),
            ),
            rx.accordion.root(
                rx.accordion.item(
                    header=rx.accordion.header(
                        rx.accordion.trigger(
                            rx.cond(
                                MemoState.is_open,
                                rx.text("Hide", id="trigger-hide"),
                                rx.text("Show", id="trigger-show"),
                            ),
                            id="accordion-trigger",
                        ),
                    ),
                    content=rx.accordion.content(rx.text("body")),
                    value="item-1",
                ),
            ),
            rx.text(MemoState.counter, id="counter"),
        )

    app = rx.App()
    app.add_page(index)


@pytest.fixture(scope="module")
def memo_app(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[AppHarness, None, None]:
    """Run the memoization edge-cases app under an AppHarness.

    Args:
        tmp_path_factory: Pytest fixture for creating temporary directories.

    Yields:
        The running harness.
    """
    with AppHarness.create(
        root=tmp_path_factory.mktemp("memo_edge_cases"),
        app_source=MemoEdgeCasesApp,
    ) as harness:
        yield harness


def test_accordion_trigger_with_stateful_cond_updates(
    memo_app: AppHarness, page: Page
) -> None:
    """AccordionTrigger holding a stateful cond updates on state changes.

    Args:
        memo_app: Running app harness.
        page: Playwright page.
    """
    assert memo_app.frontend_url is not None
    page.goto(memo_app.frontend_url)

    expect(page.locator("#trigger-show")).to_have_text("Show")
    expect(page.locator("#trigger-hide")).to_have_count(0)

    page.click("#toggle")
    expect(page.locator("#trigger-hide")).to_have_text("Hide")
    expect(page.locator("#trigger-show")).to_have_count(0)

    # Bumping an unrelated counter must not desync the trigger render.
    page.click("#bump")
    expect(page.locator("#counter")).to_have_text("1")
    expect(page.locator("#trigger-hide")).to_have_text("Hide")

    page.click("#toggle")
    expect(page.locator("#trigger-show")).to_have_text("Show")


def _document_contains(page: Page, marker: str) -> bool:
    """Whether any ``<title>`` or ``<style>`` element contains ``marker``.

    ``<title>``/``<style>`` content is metadata, not "visible" text, so the
    Locator ``has_text`` filter skips them. Inspect text content via JS.

    Args:
        page: Playwright page.
        marker: Substring to look for in title/style element text content.

    Returns:
        True if any title/style element's textContent contains the marker.
    """
    return page.evaluate(
        """(marker) => {
            const els = document.querySelectorAll('title, style');
            return Array.from(els).some(el => (el.textContent || '').includes(marker));
        }""",
        marker,
    )


def test_title_element_renders_stateful_var_as_text(
    memo_app: AppHarness, page: Page
) -> None:
    """``rx.el.title(state_var)`` writes the state value as the title's text.

    Verified by reading the title element's textContent directly. A passing
    test means the state value lands as the title's text node, not a JSX
    component child that would be stringified.

    Args:
        memo_app: Running app harness.
        page: Playwright page.
    """
    assert memo_app.frontend_url is not None
    page.goto(memo_app.frontend_url)
    page.wait_for_selector("#trigger-show")

    assert _document_contains(page, "memo-title-home")
    assert not _document_contains(page, "memo-title-about")

    page.click("#set-title")
    page.wait_for_function(
        """() => Array.from(document.querySelectorAll('title'))
            .some(el => (el.textContent || '').includes('memo-title-about'))""",
        timeout=5000,
    )
    assert _document_contains(page, "memo-title-about")
    assert not _document_contains(page, "memo-title-home")


def test_style_element_renders_stateful_css_as_text(
    memo_app: AppHarness, page: Page
) -> None:
    """``rx.el.style(state_var)`` writes the state value as the stylesheet text.

    Uses a unique marker substring so the test does not collide with Emotion
    or Sonner stylesheets that also live in the document.

    Args:
        memo_app: Running app harness.
        page: Playwright page.
    """
    assert memo_app.frontend_url is not None
    page.goto(memo_app.frontend_url)
    page.wait_for_selector("#trigger-show")

    assert _document_contains(page, "memo-css-light")
    assert not _document_contains(page, "memo-css-dark")

    page.click("#set-css")
    page.wait_for_function(
        """() => Array.from(document.querySelectorAll('style'))
            .some(el => (el.textContent || '').includes('memo-css-dark'))""",
        timeout=5000,
    )
    assert _document_contains(page, "memo-css-dark")
    assert not _document_contains(page, "memo-css-light")
