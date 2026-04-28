"""Dev-only frontend inspector.

The inspector maps rendered DOM nodes back to the Python ``Component`` call
site that produced them. Each piece is independently testable:

- ``state`` toggles the global enabled flag.
- ``capture`` walks the call stack and records the user-code frame.
- ``emit`` writes the lookup table consumed by the browser script.
- ``shortcut`` parses the keyboard shortcut configured in ``rx.Config``.

The browser-side counterpart lives under ``reflex_base/assets/inspector``.
"""

from . import capture, emit, shortcut, state

__all__ = ["capture", "emit", "shortcut", "state"]
