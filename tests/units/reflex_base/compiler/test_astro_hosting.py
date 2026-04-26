"""Unit tests for per-host rewrite artifacts (Astro target).

Covers ``packages/reflex-base/src/reflex_base/compiler/astro_hosting.py``.
"""

from __future__ import annotations

import json

import pytest
from reflex_base.compiler.astro_hosting import (
    DEFAULT_404_HTML,
    _normalize_route_pattern,
    emit_404_html,
    emit_astro_hosting_artifacts,
    emit_cloudflare_redirects,
    emit_netlify_redirects,
    emit_nginx_snippet,
    emit_vercel_json,
)


@pytest.mark.parametrize(
    ("route", "expected"),
    [
        ("/", "/"),
        ("/foo", "/foo"),
        ("/foo/bar", "/foo/bar"),
        ("/blog/[slug]", "/blog/:slug"),
        ("/blog/[[slug]]", "/blog/:slug?"),
        ("/docs/[...path]", "/docs/*"),
        ("/docs/[[...path]]", "/docs/*"),
        ("/[...catchall]", "/*"),
    ],
)
def test_normalize_route_pattern_table(route: str, expected: str):
    assert _normalize_route_pattern(route) == expected


def test_emit_404_html_default():
    artifact = emit_404_html()
    assert artifact.path == "public/404.html"
    assert "<!doctype html>" in artifact.contents
    assert "404" in artifact.contents


def test_emit_404_html_custom():
    artifact = emit_404_html(contents="<h1>oops</h1>")
    assert artifact.contents == "<h1>oops</h1>"


def test_default_404_html_baseline():
    assert "<!doctype html>" in DEFAULT_404_HTML
    assert "404" in DEFAULT_404_HTML


def test_emit_netlify_redirects_includes_404_fallback():
    artifact = emit_netlify_redirects(["/", "/about"])
    assert artifact.path == "public/_redirects"
    assert "/* /404.html 404" in artifact.contents
    assert "/about" in artifact.contents


def test_emit_netlify_redirects_catchall_uses_index_html():
    artifact = emit_netlify_redirects(["/docs/[...path]"])
    assert "/docs/*" in artifact.contents
    assert "/docs/index.html" in artifact.contents


def test_emit_netlify_redirects_dedupes_repeats():
    artifact = emit_netlify_redirects(["/", "/", "/foo"])
    # Each unique route appears exactly once. "/" routes to "/index.html" and
    # "/foo" routes to "/foo/index.html"; the duplicate "/" is collapsed.
    lines = [
        line for line in artifact.contents.splitlines() if line and "404" not in line
    ]
    assert len(lines) == 2
    assert any(line.startswith("/ ") for line in lines)
    assert any(line.startswith("/foo ") for line in lines)


def test_emit_cloudflare_redirects_matches_netlify():
    a = emit_netlify_redirects(["/foo"])
    b = emit_cloudflare_redirects(["/foo"])
    assert a.contents == b.contents
    assert a.path == b.path


def test_emit_vercel_json_emits_catchall_rewrites():
    artifact = emit_vercel_json(["/", "/docs/[...path]", "/blog/[slug]"])
    assert artifact.path == "public/vercel.json"
    payload = json.loads(artifact.contents)
    assert payload["cleanUrls"] is True
    assert payload["trailingSlash"] is False
    sources = [r["source"] for r in payload["rewrites"]]
    assert "/docs/*" in sources
    # Required dynamic segments do not need a host rewrite (Vercel resolves
    # them statically); only catchalls do.
    assert "/blog/:slug" not in sources
    # Trailing 404 fallback always present.
    assert any(r["destination"] == "/404.html" for r in payload["rewrites"])


def test_emit_nginx_snippet_includes_try_files_fallback():
    artifact = emit_nginx_snippet([])
    assert artifact.path == "public/nginx.conf"
    assert "try_files $uri $uri/ $uri.html /index.html =404;" in artifact.contents
    assert "error_page 404 /404.html;" in artifact.contents


def test_emit_nginx_snippet_emits_catchall_blocks():
    artifact = emit_nginx_snippet(["/", "/docs/[...path]"])
    assert "location ^~ /docs/" in artifact.contents
    assert "/docs/index.html" in artifact.contents


def test_emit_astro_hosting_artifacts_default_set():
    artifacts = emit_astro_hosting_artifacts(["/"])
    paths = [a.path for a in artifacts]
    assert "public/404.html" in paths
    assert "public/_redirects" in paths
    assert "public/vercel.json" in paths
    assert "public/nginx.conf" in paths


def test_emit_astro_hosting_artifacts_can_skip_individual_files():
    artifacts = emit_astro_hosting_artifacts(
        ["/"],
        include_404_html=False,
        include_netlify=False,
        include_vercel=False,
        include_nginx=False,
    )
    assert artifacts == []
