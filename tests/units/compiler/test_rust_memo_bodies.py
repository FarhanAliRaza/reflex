"""Phase 2 Part C: ``CompilerSession.take_memo_bodies()`` API."""

from __future__ import annotations

from reflex.compiler.session import CompilerSession


def test_take_memo_bodies_empty_session_returns_empty_dict() -> None:
    """A fresh session has nothing in the memo-body collector."""
    sess = CompilerSession()
    assert sess.take_memo_bodies() == {}


def test_take_memo_bodies_is_idempotent_when_empty() -> None:
    """Calling repeatedly on an empty collector stays empty (no flapping)."""
    sess = CompilerSession()
    first = sess.take_memo_bodies()
    second = sess.take_memo_bodies()
    third = sess.take_memo_bodies()
    assert first == {} == second == third


def test_take_memo_bodies_returns_plain_dict() -> None:
    """Wrapper must return a Python ``dict``, not the raw Rust PyDict view.

    Phase 2 Part D consumes the result and may mutate it (pop/iterate);
    a plain dict avoids surprises if the Rust binding changes semantics.
    """
    sess = CompilerSession()
    result = sess.take_memo_bodies()
    assert type(result) is dict


def test_distinct_sessions_share_thread_local_storage() -> None:
    """Storage is thread-local, not per-session-instance.

    This is the documented contract: ``read_page`` doesn't get a session
    reference, so the collector lives in thread-local state. Two
    sessions on the same thread therefore share it. The per-page reset
    in ``compile_page_from_component`` is what keeps pages isolated in
    practice.

    A fresh session draining still sees ``{}`` because no ``read_page``
    has run yet — but if either session were to invoke
    ``compile_page_from_component`` first, the other's drain afterwards
    would also be empty (post-drain). Encoded here to lock the
    semantics in case Part B ever wonders.
    """
    sess_a = CompilerSession()
    sess_b = CompilerSession()
    assert sess_a.take_memo_bodies() == {}
    assert sess_b.take_memo_bodies() == {}


# NOTE: populated-collector coverage is deferred to Phase 2 Part B,
# which is where the ``read_page`` walk gains the ``add(...)`` call.
# Adding a test-only PyO3 hook just to populate the cell from Python
# would force public-API exposure of an internal collector; Part B's
# end-to-end integration test will exercise the populated path through
# the real `compile_page_from_component` -> `take_memo_bodies()` flow.
