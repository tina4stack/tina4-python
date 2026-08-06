"""``asgi()`` MUST REGISTER ROUTES. THE BARE ``app`` DOES NOT.

Tina4 exposes an ASGI 3 callable so you can run it under uvicorn, hypercorn,
granian or daphne instead of ``tina4 serve``. Route discovery, though, happens
inside ``run()`` - so pointing a server straight at ``tina4_python.core.server:app``
starts a perfectly working application with NO ROUTES IN IT.

Measured against a real uvicorn before ``asgi()`` existed:

    uvicorn tina4_python.core.server:app   ->  GET /hello  404
    discover first, then serve `app`       ->  GET /hello  200

That is the worst shape of failure: the server boots, the health endpoint
answers, and every application route 404s. Nothing in the logs says why.

``asgi()`` is the supported bootstrap, and this file exists so it cannot
quietly stop discovering. The negative case is deliberately kept: if the bare
``app`` ever starts discovering on its own, this file fails and says so, rather
than leaving two bootstraps that silently do the same thing.

NO MOCKS: the real discovery over a real temp project, the real router.
"""
import os
import pathlib
import sys

import pytest

from tina4_python.core.router import Router


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A real project tree with one route file on disk."""
    routes = tmp_path / "src" / "routes"
    routes.mkdir(parents=True)
    (routes / "probe.py").write_text(
        "from tina4_python.core.router import get\n"
        "\n"
        "@get('/asgi-probe')\n"
        "def probe(request, response):\n"
        "    return response('probe ok')\n"
    )
    monkeypatch.chdir(tmp_path)
    # chdir alone is not enough: discovery IMPORTS each route file, and an
    # already-running interpreter does not put the cwd on sys.path. A real
    # project gets its root there because `tina4 serve` starts from it.
    monkeypatch.syspath_prepend(str(tmp_path))
    Router.clear()          # no route state leaking in from another test
    yield tmp_path
    Router.clear()


def _registered_paths():
    """Every path the router currently knows about.

    Router.get_routes() is the public accessor and returns a flat list of
    dicts. A first draft of this helper read ``Router.routes``, which does not
    exist - it returned None, every lookup found an empty set, and the tests
    failed for a reason that had nothing to do with the code under test.
    """
    return {r["path"] for r in Router.get_routes() if isinstance(r, dict) and "path" in r}


def test_asgi_returns_a_callable(project):
    """It must hand back something an ASGI server can actually run."""
    from tina4_python.core.server import asgi

    application = asgi()
    assert callable(application), "asgi() must return the ASGI callable"


def test_asgi_discovers_routes_from_src(project):
    """The whole reason the function exists."""
    from tina4_python.core.server import asgi

    before = _registered_paths()
    assert "/asgi-probe" not in before, "the probe route must not be registered yet"

    asgi()

    assert "/asgi-probe" in _registered_paths(), (
        "asgi() did not discover src/routes, so every application route would "
        "404 under uvicorn while the server looked healthy"
    )


def test_asgi_takes_a_custom_root(project):
    """A project that does not use src/ must still be able to boot."""
    from tina4_python.core.server import asgi

    other = project / "application" / "routes"
    other.mkdir(parents=True)
    # Discovery imports the file as a module, so the root has to be a package -
    # the same requirement src/ already meets in a scaffolded project.
    (project / "application" / "__init__.py").write_text("")
    (other / "__init__.py").write_text("")
    (other / "custom.py").write_text(
        "from tina4_python.core.router import get\n"
        "\n"
        "@get('/custom-root')\n"
        "def custom(request, response):\n"
        "    return response('custom ok')\n"
    )

    asgi("application")

    assert "/custom-root" in _registered_paths(), (
        "asgi(root_dir) ignored the directory it was given"
    )


def test_the_bare_app_is_still_just_the_callable(project):
    """The negative case, kept on purpose.

    ``app`` is the raw ASGI callable and discovers nothing. If that ever
    changes, ``asgi()`` is redundant and this file should be rewritten rather
    than left asserting a distinction that no longer exists.
    """
    from tina4_python.core.server import app

    assert callable(app)
    assert "/asgi-probe" not in _registered_paths(), (
        "importing the bare app registered routes. asgi() and app now do the "
        "same thing, so one of them should go"
    )
