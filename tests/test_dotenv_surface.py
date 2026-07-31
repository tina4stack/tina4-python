# Feature 1, step 5: the dotenv SURFACE is the same shape in all four.
"""
The parser behaviour was reconciled on 2026-07-30 and is pinned by the shared
corpus. The CALL SHAPE was not, and that is what these lock in.

Two defects this closes:

1. `load` took a FILE in Python, PHP and Node but a DIRECTORY in Ruby, so the
   obvious cross-framework call was wrong in three places or one, depending on
   which you learned first. The directory form is canonical because it
   ENCAPSULATES the precedence rule (real-env > .env.local > .env). That rule
   used to be the caller's job, duplicated at every boot site, and getting it
   wrong lets a stray gitignored .env.local beat a production variable.
2. Ruby's helpers were reachable only as `Tina4::Env.*`, so `Tina4.load_env`
   raised NoMethodError while the other three exposed a plain function.

NO MOCKS and no doubles: a .env is a file, so the real dependency is a real file
in a real temp directory, and the real process environment.

Identical case names in all four frameworks:
  tina4-php/tests/DotEnvSurfaceTest.php
  tina4-ruby/spec/dotenv_surface_spec.rb
  tina4-nodejs/test/dotenvSurface.test.ts
"""
import os
import tempfile
from pathlib import Path

import pytest

import tina4_python.dotenv as dotenv_module
from tina4_python.dotenv import load_env


@pytest.fixture
def env_root():
    """A real directory holding a real .env and .env.local."""
    with tempfile.TemporaryDirectory() as root:
        Path(root, ".env").write_text("SURFACE_BASE=from_env\nSURFACE_SHARED=from_env\n")
        Path(root, ".env.local").write_text("SURFACE_SHARED=from_local\nSURFACE_LOCAL=only_local\n")
        for key in ("SURFACE_BASE", "SURFACE_SHARED", "SURFACE_LOCAL"):
            os.environ.pop(key, None)
        yield root
        for key in ("SURFACE_BASE", "SURFACE_SHARED", "SURFACE_LOCAL"):
            os.environ.pop(key, None)


def test_load_env_accepts_a_root_directory(env_root):
    """POSITIVE: the canonical form. A directory loads BOTH files, in order."""
    result = load_env(env_root)

    assert os.environ["SURFACE_BASE"] == "from_env", "the .env was not read"
    assert os.environ["SURFACE_LOCAL"] == "only_local", "the .env.local was not read"
    assert result["SURFACE_BASE"] == "from_env"


def test_load_env_directory_form_gives_env_local_precedence(env_root):
    """
    The whole reason the directory form exists: .env.local beats .env. A caller
    doing this by hand in the wrong order gets the opposite, silently.
    """
    load_env(env_root)
    assert os.environ["SURFACE_SHARED"] == "from_local"


def test_load_env_still_accepts_a_single_file(env_root):
    """NEGATIVE: the directory form must not break the file form."""
    load_env(str(Path(env_root, ".env")))

    assert os.environ["SURFACE_BASE"] == "from_env"
    assert "SURFACE_LOCAL" not in os.environ, (
        "naming ONE file must read only that file - the caller owns the ordering"
    )


def test_load_env_is_reachable_from_the_top_level_namespace():
    """
    NEGATIVE: the obvious call must not raise. This is the case that was red in
    Ruby, where the helpers lived only under Tina4::Env.
    """
    for name in (
        "load_env", "get_env", "require_env", "has_env", "all_env", "reset_env", "is_truthy",
    ):
        assert hasattr(dotenv_module, name), f"{name} is not reachable at the top level"
        assert callable(getattr(dotenv_module, name))


def test_a_missing_env_local_is_not_an_error():
    """A fresh checkout has no .env.local, and the directory form reads it anyway."""
    with tempfile.TemporaryDirectory() as root:
        Path(root, ".env").write_text("SOLO=1\n")
        os.environ.pop("SOLO", None)
        load_env(root)
        assert os.environ["SOLO"] == "1"
        os.environ.pop("SOLO", None)
