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

from tina4_python.frond.engine import Frond, TemplateSyntaxError


@pytest.mark.timeout(10)
def test_malformed_endblock_in_child_fails_loud_without_hanging(tmp_path):
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
    # Must FAIL LOUD (tina4#286/#290) — still bounded, so a reintroduced hang
    # trips the timeout rather than hanging the suite (tina4#271).
    with pytest.raises(TemplateSyntaxError) as exc:
        engine.render("page.twig", {})
    assert "content" in str(exc.value)


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
def test_extract_blocks_raises_on_a_malformed_block():
    # Unit-level: a malformed (unclosed) block fails loud (tina4#286/#290),
    # still bounded so a reintroduced hang trips the timeout (tina4#271).
    engine = Frond()
    # An unclosed outer block whose first {% endblock %} belongs to a nested
    # block leaves the outer open → raise.
    with pytest.raises(TemplateSyntaxError):
        engine._extract_blocks(
            "{% block bad %}no close... {% block good %}Y{% endblock %}"
        )

    # A single unclosed block raises too.
    with pytest.raises(TemplateSyntaxError):
        engine._extract_blocks("{% block lonely %}body with no end")
