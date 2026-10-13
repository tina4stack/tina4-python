# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""errors/302.twig puts redirect_url into both an <a href> and a
<meta http-equiv="refresh"> url. A tainted value must not be able to run script
(javascript:/data:/vbscript:) or bounce the user off-site via a scheme-relative
//host target. The template collapses anything that is not a same-site relative
path or an explicit http/https URL to "/".

Real Frond render against the shipped framework template — no mocks. Case names
match the sibling regression in tina4-php/tests/RedirectTemplateSafetyTest.php.
"""
import html as html_mod
import re

import pytest

from tina4_python.crud.page_render import render_template


def _rendered_urls(redirect_url):
    html = render_template("errors/302.twig", {"redirect_url": redirect_url, "title": "t"})
    href = re.search(r'<a href="([^"]*)"', html).group(1)
    meta = re.search(r'url=([^"]*)">', html).group(1)
    return href, meta


DANGEROUS = [
    "javascript:alert(1)",
    "JAVASCRIPT:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox(1)",
    "//evil.example.com/pwn",
    "",
    "evilsite",
]

SAFE = [
    ("/dashboard?x=1", "/dashboard?x=1"),
    ("/", "/"),
    ("https://tina4.com/ok", "https://tina4.com/ok"),
    ("http://tina4.com/ok", "http://tina4.com/ok"),
]


@pytest.mark.parametrize("url", DANGEROUS)
def test_dangerous_redirect_collapses_to_root(url):
    href, meta = _rendered_urls(url)
    assert href == "/", f"href must be neutralised for: {url}"
    assert meta == "/", f"meta refresh must be neutralised for: {url}"


@pytest.mark.parametrize("url,expected", SAFE)
def test_safe_redirect_is_preserved(url, expected):
    escaped = html_mod.escape(expected, quote=True)
    href, meta = _rendered_urls(url)
    assert href == escaped, f"href must preserve a safe target: {url}"
    assert meta == escaped, f"meta refresh must preserve a safe target: {url}"


def test_relative_path_with_metacharacters_is_escaped_not_broken_out():
    href, _ = _rendered_urls('/search?q="><img src=x onerror=alert(1)>')
    assert href.startswith("/search?q=")
    assert "<img" not in href
    assert '"' not in href
    assert "&quot;" in href
