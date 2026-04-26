"""Per-host rewrite/404 artifacts for the Astro frontend target.

Astro is configured with ``output: "static"``, so the generated ``dist`` is a
plain static site. Hosts handle unknown / dynamic-catchall routes differently;
this module renders the host-specific files so the same Reflex app can deploy
to ASGI mounts, Netlify, Cloudflare Pages, Vercel, S3+CloudFront, GitHub
Pages, or behind nginx without manual edits.

Each helper returns the `(path, contents)` pair to write under ``.web/``;
callers decide which subset of hosts to emit (by default
:func:`emit_astro_hosting_artifacts` emits everything that is safe to ship
unconditionally, e.g. a ``404.html`` and a Netlify ``_redirects``).
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from reflex_base.compiler.astro import AstroPageArtifact

DEFAULT_404_HTML = (
    "<!doctype html>\n"
    '<html lang="en">\n'
    "  <head>\n"
    '    <meta charset="UTF-8" />\n'
    "    <title>404 - Not Found</title>\n"
    "    <style>body{font-family:system-ui,sans-serif;text-align:center;"
    "padding:4rem 1rem;color:#222;}</style>\n"
    "  </head>\n"
    "  <body>\n"
    "    <h1>404</h1>\n"
    "    <p>The page you requested could not be found.</p>\n"
    "  </body>\n"
    "</html>\n"
)


def _normalize_route_pattern(route: str) -> str:
    """Normalize a Reflex route into a host-redirect path pattern.

    Args:
        route: A Reflex route (e.g. ``"/blog/[slug]"`` or ``"/docs/[...path]"``).

    Returns:
        A pattern string suitable for inclusion in ``_redirects`` or a
        Vercel rewrite rule. Catchalls become ``/*``; required dynamic
        segments become ``:param``.
    """
    # Catchall (optional or required): collapse trailing ``[...x]`` /
    # ``[[...x]]`` segment to a host wildcard ``/*``. The optional form must
    # be checked first because it shares a prefix with the required form.
    catchall_prefix = None
    if "[[..." in route:
        catchall_prefix = route.split("[[...", 1)[0].rstrip("/")
    elif "[..." in route:
        catchall_prefix = route.split("[...", 1)[0].rstrip("/")
    if catchall_prefix is not None:
        return "/*" if not catchall_prefix else f"{catchall_prefix}/*"
    # Required dynamic segment: /blog/[slug] -> /blog/:slug
    out_parts: list[str] = []
    for segment in route.split("/"):
        if not segment:
            out_parts.append("")
            continue
        if segment.startswith("[[") and segment.endswith("]]"):
            out_parts.append(f":{segment[2:-2]}?")
            continue
        if segment.startswith("[") and segment.endswith("]"):
            out_parts.append(f":{segment[1:-1]}")
            continue
        out_parts.append(segment)
    normalized = "/".join(out_parts)
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    return normalized


def emit_404_html(*, contents: str = DEFAULT_404_HTML) -> AstroPageArtifact:
    """Emit a top-level ``404.html`` fallback served by static hosts.

    Astro will already emit ``src/pages/404.astro`` -> ``404.html`` when the
    user defines a 404 page. This helper provides a safe default for hosts
    (GitHub Pages, S3 with custom error doc) that fall back on a top-level
    ``404.html``. Callers may override the contents.

    Args:
        contents: The HTML for the 404 page. Defaults to a minimal stylesheet.

    Returns:
        The :class:`AstroPageArtifact`.
    """
    return AstroPageArtifact(path="public/404.html", contents=contents)


def emit_netlify_redirects(
    routes: Sequence[str], *, status: int = 200
) -> AstroPageArtifact:
    """Emit ``_redirects`` for Netlify and Cloudflare Pages.

    For each prebuilt route the file emits a no-op ``200`` rule so the host
    serves the prebuilt HTML. Catchall routes additionally emit a wildcard
    rewrite that points at the catchall's ``index.html`` so unknown paths
    under the catchall prefix still resolve. Unknown paths fall through to a
    final ``/* /404.html 404`` line.

    Args:
        routes: The Reflex route list to write rules for.
        status: HTTP status to use for prebuilt rules. ``200`` performs a
            rewrite (URL stays the same), ``301``/``302`` redirect.

    Returns:
        The :class:`AstroPageArtifact` at ``public/_redirects``.
    """
    lines: list[str] = []
    seen: set[str] = set()
    for route in routes:
        pattern = _normalize_route_pattern(route)
        if pattern in seen:
            continue
        seen.add(pattern)
        if pattern in ("/", "/*"):
            target = "/index.html"
        elif pattern.endswith("/*"):
            base = pattern[: -len("/*")]
            target = f"{base}/index.html"
        else:
            target = f"{pattern}/index.html"
        lines.append(f"{pattern} {target} {status}")
    lines.append("/* /404.html 404")
    return AstroPageArtifact(path="public/_redirects", contents="\n".join(lines) + "\n")


def emit_vercel_json(routes: Sequence[str]) -> AstroPageArtifact:
    """Emit ``vercel.json`` rewrites for catchall + dynamic routes.

    Vercel serves prebuilt files automatically; this file only adds
    rewrites for routes whose unknown paths must be served by the
    catchall's ``index.html`` (e.g. ``/docs/*`` -> ``/docs/index.html``).
    A trailing rewrite directs every other unknown path at ``/404.html``.

    Args:
        routes: The Reflex route list to write rules for.

    Returns:
        The :class:`AstroPageArtifact` at ``public/vercel.json``.
    """
    rewrites: list[dict[str, str]] = []
    seen: set[str] = set()
    for route in routes:
        pattern = _normalize_route_pattern(route)
        if pattern in seen or not pattern.endswith("/*"):
            continue
        seen.add(pattern)
        base = pattern[: -len("/*")]
        rewrites.append({
            "source": pattern,
            "destination": f"{base}/index.html",
        })
    rewrites.append({"source": "/(.*)", "destination": "/404.html"})
    payload = {"cleanUrls": True, "trailingSlash": False, "rewrites": rewrites}
    return AstroPageArtifact(
        path="public/vercel.json",
        contents=json.dumps(payload, indent=2) + "\n",
    )


def emit_nginx_snippet(routes: Sequence[str]) -> AstroPageArtifact:
    """Emit an nginx config snippet that serves the static build.

    Designed to be ``include``-d from a server block. Tries the request URI
    first, then the directory + ``index.html``, then falls back to
    ``/404.html``. Catchall routes get an explicit rewrite so unknown paths
    under the prefix resolve to that catchall's ``index.html``.

    Args:
        routes: The Reflex route list (catchalls only generate rewrites).

    Returns:
        The :class:`AstroPageArtifact` at ``public/nginx.conf``.
    """
    rewrite_lines: list[str] = []
    seen: set[str] = set()
    for route in routes:
        pattern = _normalize_route_pattern(route)
        if pattern in seen or not pattern.endswith("/*"):
            continue
        seen.add(pattern)
        base = pattern[: -len("/*")]
        # nginx `^~` prefix-location, longest-match wins.
        rewrite_lines.append(
            f"location ^~ {base}/ {{ try_files $uri $uri/ {base}/index.html =404; }}"
        )
    body = (
        '# Generated by Reflex (frontend_target="astro"). Include from a server block.\n'
        + "\n".join(rewrite_lines)
        + ("\n" if rewrite_lines else "")
        + "location / {\n"
        "    try_files $uri $uri/ $uri.html /index.html =404;\n"
        "}\n"
        "error_page 404 /404.html;\n"
    )
    return AstroPageArtifact(path="public/nginx.conf", contents=body)


def emit_cloudflare_redirects(
    routes: Sequence[str], *, status: int = 200
) -> AstroPageArtifact:
    """Cloudflare Pages also reads a ``_redirects`` file at the build root.

    The format is identical to Netlify's, so :func:`emit_netlify_redirects`
    output is reused. Provided as a separate helper for callers that want
    to write the file at the Cloudflare-specific path.

    Args:
        routes: The Reflex route list.
        status: HTTP status to use for prebuilt rules.

    Returns:
        The :class:`AstroPageArtifact` at ``public/_redirects``.
    """
    return emit_netlify_redirects(routes, status=status)


def emit_astro_hosting_artifacts(
    routes: Sequence[str],
    *,
    include_404_html: bool = True,
    include_netlify: bool = True,
    include_vercel: bool = True,
    include_nginx: bool = True,
) -> list[AstroPageArtifact]:
    """Emit the host-rewrite artifact set for a built Astro site.

    Defaults are conservative and additive: every artifact lives under
    ``public/`` so unrelated hosts simply ignore the files they do not
    understand.

    Args:
        routes: The Reflex route list. Catchalls/dynamic routes drive
            host rewrite rules; static routes are no-ops.
        include_404_html: Emit a baseline ``404.html`` fallback.
        include_netlify: Emit ``_redirects`` (Netlify, Cloudflare Pages).
        include_vercel: Emit ``vercel.json``.
        include_nginx: Emit ``nginx.conf``.

    Returns:
        The list of :class:`AstroPageArtifact` instances.
    """
    artifacts: list[AstroPageArtifact] = []
    if include_404_html:
        artifacts.append(emit_404_html())
    if include_netlify:
        artifacts.append(emit_netlify_redirects(routes))
    if include_vercel:
        artifacts.append(emit_vercel_json(routes))
    if include_nginx:
        artifacts.append(emit_nginx_snippet(routes))
    return artifacts
