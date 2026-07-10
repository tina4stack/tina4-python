"""Regression: tina4_python.__version__ must match the single source of truth.

The maintainer once bumped the PyPI version in pyproject.toml but not the
hardcoded __version__ constant, so the dev toolbar and docs._detect_version
under-reported for several releases. __version__ is now derived, and this test
locks it to pyproject.toml so the two can never drift again.
"""
import pathlib
import tomllib

import tina4_python


def _pyproject_version() -> str:
    pp = pathlib.Path(tina4_python.__file__).resolve().parent.parent / "pyproject.toml"
    with pp.open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def test_version_matches_pyproject():
    assert tina4_python.__version__ == _pyproject_version()


def test_version_is_not_a_stale_placeholder():
    # A non-empty dotted version, never the ""/"0.0.0" a broken resolve gives.
    assert tina4_python.__version__ not in ("", "0.0.0")
    assert tina4_python.__version__.count(".") >= 2


def test_resolver_reads_pyproject_in_a_checkout():
    # In a source checkout the repo pyproject is authoritative (installed
    # metadata can lag an un-synced editable install).
    assert tina4_python._resolve_version() == _pyproject_version()
