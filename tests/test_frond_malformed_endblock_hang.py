# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Regression for tina4#271: a child template whose last ``{% endblock %}`` is
malformed (its closing ``}`` missing) made ``Frond._extract_blocks`` loop forever,
so the render never returned. These exercise the REAL engine against REAL template
files on disk — no mocks — and are bounded so a reintroduced hang fails the test
fast instead of hanging the suite until the global timeout.
"""

import pytest

from tina4_python.frond.engine import Frond


@pytest.mark.timeout(10)
def test_malformed_endblock_in_child_does_not_hang(tmp_path):
    (tmp_path / "base.twig").write_text(
        "<html>{% block content %}default{% endblock %}</html>"
    )
    # The final tag is missing its closing brace: `{% endblock %` not `{% endblock %}`.
    (tmp_path / "page.twig").write_text(
        '{% extends "base.twig" %}\n'
        "{% block content %}\n"
        "<p>hi</p>\n"
        "{% endblock %"
    )

    engine = Frond(template_dir=str(tmp_path))
    # Must RETURN (not hang, not raise) on a malformed template.
    result = engine.render("page.twig", {})
    assert isinstance(result, str)


@pytest.mark.timeout(10)
def test_wellformed_inheritance_still_renders(tmp_path):
    # The fix must not regress normal inheritance: a well-formed child's block
    # body replaces the parent's default.
    (tmp_path / "base.twig").write_text(
        "<html>{% block content %}default{% endblock %}</html>"
    )
    (tmp_path / "page.twig").write_text(
        '{% extends "base.twig" %}\n'
        "{% block content %}<p>hi</p>{% endblock %}"
    )

    engine = Frond(template_dir=str(tmp_path))
    result = engine.render("page.twig", {})
    assert "<p>hi</p>" in result
    assert "default" not in result


@pytest.mark.timeout(10)
def test_extract_blocks_skips_a_malformed_block_but_finds_later_ones():
    # Unit-level: a malformed (unclosed) block is skipped, and a well-formed block
    # after it is still extracted — progress is made, no infinite loop.
    engine = Frond()
    blocks = engine._extract_blocks(
        "{% block bad %}no close... {% block good %}Y{% endblock %}"
    )
    assert blocks == {"good": "Y"}

    # A single unclosed block yields nothing and still returns.
    assert engine._extract_blocks("{% block lonely %}body with no end") == {}
