"""Regression: tina4_python.__version__ must match the single source of truth.

The maintainer once bumped the PyPI version in pyproject.toml but not the
hardcoded __version__ constant, so the dev toolbar and docs._detect_version
under-reported for several releases. __version__ is now derived, and this test
locks it to pyproject.toml so the two can never drift again.
"""
import inspect
import pathlib
import re
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


def _floor_literal() -> str:
    """The hardcoded fallback inside _resolve_version, read from the source.

    Read from source rather than called, because in a checkout the function
    returns via path 1 and never reaches the literal -- which is exactly why
    the literal was free to rot unnoticed.
    """
    source = inspect.getsource(tina4_python._resolve_version)
    literals = re.findall(r'return\s+"(\d+\.\d+\.\d+)"', source)
    assert literals, "no floor literal found in _resolve_version"
    return literals[-1]


def test_floor_literal_tracks_pyproject():
    """The last-resort literal must be bumped with the release.

    This is the bug the Docker boot gate surfaced. Both real paths can miss in
    an installed package: there is no pyproject.toml beside it (path 1), and the
    image build used to prune the dist-info that importlib.metadata reads
    (path 2). The published tina4-python:3.13.92 image therefore served this
    literal -- reading "3.13.56", 36 releases stale, because no test held it.

    Fixing the Dockerfile stops path 2 missing. This test makes the literal
    harmless even if it misses again.
    """
    assert _floor_literal() == _pyproject_version(), (
        f"the floor literal {_floor_literal()!r} in _resolve_version does not match "
        f"pyproject version {_pyproject_version()!r} -- bump it with the release"
    )
