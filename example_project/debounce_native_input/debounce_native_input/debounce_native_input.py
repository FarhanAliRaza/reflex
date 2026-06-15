"""Example app to verify rx.debounce_input works with native DOM elements.

This reproduces reflex-dev/reflex#6637: wrapping native elements such as
``rx.el.input`` / ``rx.el.textarea`` in ``rx.debounce_input`` previously
emitted an unquoted ``element={input}`` and crashed with
``ReferenceError: input is not defined``. The element prop must render as the
string literal ``element={"input"}``.
"""

import reflex as rx


class State(rx.State):
    """Holds the debounced values typed by the user."""

    native_input: str = ""
    native_textarea: str = ""
    library_input: str = ""

    @rx.event
    def set_native_input(self, value: str):
        self.native_input = value

    @rx.event
    def set_native_textarea(self, value: str):
        self.native_textarea = value

    @rx.event
    def set_library_input(self, value: str):
        self.library_input = value


def index() -> rx.Component:
    return rx.vstack(
        rx.heading("debounce_input + native DOM elements"),
        # Native input element (the regression from #6637).
        rx.debounce_input(
            rx.el.input(
                placeholder="native input",
                on_change=State.set_native_input,
            ),
            debounce_timeout=300,
        ),
        rx.text(f"native input: {State.native_input}"),
        # Native textarea element.
        rx.debounce_input(
            rx.el.textarea(
                placeholder="native textarea",
                on_change=State.set_native_textarea,
            ),
            debounce_timeout=300,
        ),
        rx.text(f"native textarea: {State.native_textarea}"),
        # Library component for comparison (should keep working).
        rx.debounce_input(
            rx.input(
                placeholder="library input",
                on_change=State.set_library_input,
            ),
            debounce_timeout=300,
        ),
        rx.text(f"library input: {State.library_input}"),
        spacing="4",
        padding="2em",
    )


app = rx.App()
app.add_page(index)
