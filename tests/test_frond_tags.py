"""Feature 53 - Frond {% include %} / {% extends %} path confinement (TAG-DEC-01).

Real templates on disk, a real secret file OUTSIDE the templates dir, and a real
symlink -- NO mocks. Every case drives the REAL Frond engine against files it
wrote to a temp directory. A legit include/extends UNDER the templates dir
renders; a `..` traversal, an absolute path, and a symlink whose realpath escapes
the templates dir are all REFUSED (a clear error, never the outside file's bytes).

Mutation proof: delete the containment guard in Frond._load (tina4_python/frond/
engine.py) and the traversal / absolute / symlink cases RENDER the outside file's
SECRET marker instead of raising -- these tests then go RED. Restore the guard and
they go green. The legit cases prove the guard discriminates (it does not blanket
-deny a real partial/parent).

Shared conformance fixture:
tina4-documentation/plan/v3/fixtures/frondtags_contract.json
"""
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from tina4_python.frond import Frond

# A marker only ever written to a file OUTSIDE the templates dir. If it ever
# appears in rendered output, confinement was bypassed and the outside file read.
SECRET = "TOP-SECRET-OUTSIDE-9f83c1"


def _make_tree():
    """Build a REAL templates dir with legit partial+base, and a REAL secret file
    OUTSIDE it. Returns (base_dir, templates_dir, secret_path)."""
    base = Path(tempfile.mkdtemp(prefix="frondtags_py_"))
    templates = base / "templates"
    (templates / "partials").mkdir(parents=True)
    (templates / "partials" / "hello.twig").write_text(
        "Hello from a real partial", encoding="utf-8")
    (templates / "base.twig").write_text(
        "[BASE {% block body %}default{% endblock %} END]", encoding="utf-8")
    secret = base / "secret.txt"          # lives OUTSIDE templates/
    secret.write_text(SECRET, encoding="utf-8")
    return base, templates, secret


class TestFrondTagsConfinement:
    """TAG-DEC-01: confine include/extends under the templates dir, all four."""

    def test_a_legit_include_renders_under_the_templates_dir(self):
        base, templates, _ = _make_tree()
        try:
            (templates / "page.twig").write_text(
                'X {% include "partials/hello.twig" %} Y', encoding="utf-8")
            out = Frond(str(templates)).render("page.twig")
            assert "Hello from a real partial" in out
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_a_legit_extends_renders_under_the_templates_dir(self):
        base, templates, _ = _make_tree()
        try:
            (templates / "child.twig").write_text(
                '{% extends "base.twig" %}{% block body %}CHILD-BODY{% endblock %}',
                encoding="utf-8")
            out = Frond(str(templates)).render("child.twig")
            assert "CHILD-BODY" in out
            assert "BASE" in out            # the parent shell rendered too
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_a_dot_dot_traversal_include_is_refused(self):
        base, templates, _ = _make_tree()
        try:
            # ../secret.txt climbs OUT of the templates dir.
            (templates / "evil.twig").write_text(
                '{% include "../secret.txt" %}', encoding="utf-8")
            with pytest.raises(ValueError, match="escape") as excinfo:
                Frond(str(templates)).render("evil.twig")
            assert SECRET not in str(excinfo.value)
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_an_absolute_path_include_is_refused(self):
        base, templates, secret = _make_tree()
        try:
            # An absolute path to the real secret file.
            (templates / "evil_abs.twig").write_text(
                '{% include "' + str(secret) + '" %}', encoding="utf-8")
            with pytest.raises(ValueError, match="escape") as excinfo:
                Frond(str(templates)).render("evil_abs.twig")
            assert SECRET not in str(excinfo.value)
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_a_symlink_escaping_the_templates_dir_is_refused(self):
        base, templates, secret = _make_tree()
        try:
            # A REAL symlink INSIDE the templates dir whose target is the secret
            # OUTSIDE it. Its name has no `..` and is not absolute, so only the
            # realpath containment can catch it.
            link = templates / "sneaky.twig"
            os.symlink(secret, link)
            (templates / "evil_link.twig").write_text(
                '{% include "sneaky.twig" %}', encoding="utf-8")
            with pytest.raises(ValueError, match="escape") as excinfo:
                Frond(str(templates)).render("evil_link.twig")
            assert SECRET not in str(excinfo.value)
        finally:
            shutil.rmtree(base, ignore_errors=True)
