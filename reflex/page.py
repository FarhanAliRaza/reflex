"""The page decorator and associated variables and functions."""

from __future__ import annotations

import sys
from collections import defaultdict
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from reflex_base.event import EventType

DECORATED_PAGES: dict[str, list[tuple[Callable, dict[str, Any]]]] = defaultdict(list)

RenderMode = Literal["static", "app", "islands"]
VALID_RENDER_MODES: tuple[str, ...] = ("static", "app", "islands")


def _validate_render_mode(
    render_mode: str | None,
    on_load: Any,
    route: str | None,
) -> None:
    """Validate render_mode and its compatibility with other page kwargs.

    Args:
        render_mode: The user-supplied render_mode value.
        on_load: The user-supplied on_load handler (if any).
        route: The page route, used for error messages.

    Raises:
        CompileError: If render_mode is invalid, or `on_load` is set on a
            non-`app` page.
    """
    from reflex_base.utils.exceptions import CompileError

    if render_mode is None:
        return
    if render_mode not in VALID_RENDER_MODES:
        msg = (
            f"Invalid render_mode={render_mode!r} on page route={route!r}. "
            f"Expected one of {VALID_RENDER_MODES}."
        )
        raise CompileError(msg)
    if on_load is not None and render_mode != "app":
        msg = (
            f"on_load is only supported in render_mode='app' on the Astro "
            f"target (page route={route!r}, render_mode={render_mode!r}). "
            f"Remove the handler or switch the page to app mode."
        )
        raise CompileError(msg)


def page(
    route: str | None = None,
    title: str | None = None,
    image: str | None = None,
    description: str | None = None,
    meta: list[Any] | None = None,
    script_tags: list[Any] | None = None,
    on_load: EventType[()] | None = None,
    render_mode: RenderMode | None = None,
):
    """Decorate a function as a page.

    rx.App() will automatically call add_page() for any method decorated with page
    when App.compile is called.

    All defaults are None because they will use the one from add_page().

    Note: the decorated functions still need to be imported.

    Args:
        route: The route to reach the page.
        title: The title of the page.
        image: The favicon of the page.
        description: The description of the page.
        meta: Additional meta to add to the page.
        on_load: The event handler(s) called when the page load.
        script_tags: scripts to attach to the page
        render_mode: Astro render mode for the page. One of:
          - "static": no Reflex runtime, no React hydration. Static state/event
            usage is rejected at compile time.
          - "app" (default on the Astro target): whole page hydrates as one React
            root. Zero-migration default for existing Reflex apps.
          - "islands": only compiler-detected or `rx.island(...)`-marked subtrees
            hydrate. The rest of the page ships as HTML.

          On the React Router target the value is accepted but only "app" is
          honored; "static"/"islands" emit a deprecation warning and fall through
          to the existing codegen path.

    Returns:
        The decorated function.
    """
    from reflex_base.config import get_config

    _validate_render_mode(render_mode, on_load, route)

    def decorator(render_fn: Callable):
        kwargs: dict[str, Any] = {}
        if route:
            kwargs["route"] = route
        if title:
            kwargs["title"] = title
        if image:
            kwargs["image"] = image
        if description:
            kwargs["description"] = description
        if meta:
            kwargs["meta"] = meta
        if script_tags:
            kwargs["script_tags"] = script_tags
        if on_load:
            kwargs["on_load"] = on_load
        if render_mode is not None:
            kwargs["render_mode"] = render_mode

        DECORATED_PAGES[get_config().app_name].append((render_fn, kwargs))

        return render_fn

    return decorator


class PageNamespace:
    """A namespace for page names."""

    DECORATED_PAGES = DECORATED_PAGES

    def __new__(
        cls,
        route: str | None = None,
        title: str | None = None,
        image: str | None = None,
        description: str | None = None,
        meta: list[Any] | None = None,
        script_tags: list[Any] | None = None,
        on_load: EventType[()] | None = None,
        render_mode: RenderMode | None = None,
    ):
        """Decorate a function as a page.

        rx.App() will automatically call add_page() for any method decorated with page
        when App.compile is called.

        All defaults are None because they will use the one from add_page().

        Note: the decorated functions still need to be imported.

        Args:
            route: The route to reach the page.
            title: The title of the page.
            image: The favicon of the page.
            description: The description of the page.
            meta: Additional meta to add to the page.
            on_load: The event handler(s) called when the page load.
            script_tags: scripts to attach to the page
            render_mode: Astro render mode for the page (see :func:`page`).

        Returns:
            The decorated function.
        """
        return page(
            route=route,
            title=title,
            image=image,
            description=description,
            meta=meta,
            script_tags=script_tags,
            on_load=on_load,
            render_mode=render_mode,
        )

    page = staticmethod(page)
    _validate_render_mode = staticmethod(_validate_render_mode)
    __file__ = __file__


page_namespace = PageNamespace
sys.modules[__name__] = page_namespace  # pyright: ignore[reportArgumentType]
