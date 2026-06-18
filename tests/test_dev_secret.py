"""Fail-safe dev secret bootstrap — tina4_python.auth.ensure_dev_secret().

In DEV (TINA4_DEBUG truthy, CI unset, not production) with a blank
TINA4_SECRET, the bootstrap mints a cryptographically-random secret, writes
it to a gitignored .env.local, and sets it in the process env for this run.

In CI (CI=true) or production it NEVER generates and NEVER writes — it emits
the actionable warning path instead. No DB is needed for any of this.
"""
import os
import re

from tina4_python.auth import ensure_dev_secret


def _clear_secret_env(monkeypatch):
    monkeypatch.delenv("TINA4_SECRET", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("TINA4_ENV", raising=False)
    monkeypatch.delenv("TINA4_DEBUG", raising=False)


class TestDevGenerates:
    def test_dev_writes_env_local_and_sets_env(self, tmp_path, monkeypatch):
        _clear_secret_env(monkeypatch)
        monkeypatch.setenv("TINA4_DEBUG", "true")   # dev
        # CI unset, TINA4_ENV unset (development), TINA4_SECRET blank.

        secret = ensure_dev_secret(cwd=str(tmp_path))

        assert secret is not None
        assert len(secret) == 64          # 32 bytes hex
        assert re.fullmatch(r"[0-9a-f]{64}", secret)
        # Set in the process env for this run.
        assert os.environ["TINA4_SECRET"] == secret
        # Persisted to .env.local (and ONLY .env.local).
        env_local = tmp_path / ".env.local"
        assert env_local.is_file()
        assert f"TINA4_SECRET={secret}" in env_local.read_text(encoding="utf-8")
        assert not (tmp_path / ".env").exists()  # never writes .env

    def test_dev_appends_to_existing_env_local(self, tmp_path, monkeypatch):
        _clear_secret_env(monkeypatch)
        monkeypatch.setenv("TINA4_DEBUG", "true")
        env_local = tmp_path / ".env.local"
        env_local.write_text("EXISTING=1", encoding="utf-8")  # no trailing newline

        secret = ensure_dev_secret(cwd=str(tmp_path))

        content = env_local.read_text(encoding="utf-8")
        assert "EXISTING=1" in content                  # preserved
        assert f"TINA4_SECRET={secret}" in content       # appended
        # Existing content without trailing newline is not corrupted onto
        # the same line as the new key.
        assert "EXISTING=1\nTINA4_SECRET=" in content

    def test_existing_secret_is_left_untouched(self, tmp_path, monkeypatch):
        _clear_secret_env(monkeypatch)
        monkeypatch.setenv("TINA4_DEBUG", "true")
        monkeypatch.setenv("TINA4_SECRET", "already-set")

        result = ensure_dev_secret(cwd=str(tmp_path))

        assert result is None                       # nothing minted
        assert os.environ["TINA4_SECRET"] == "already-set"
        assert not (tmp_path / ".env.local").exists()


class TestCiAndProdDoNotGenerate:
    def test_ci_does_not_generate_or_write(self, tmp_path, monkeypatch):
        _clear_secret_env(monkeypatch)
        monkeypatch.setenv("TINA4_DEBUG", "true")   # even in dev-debug...
        monkeypatch.setenv("CI", "true")            # ...CI must NOT generate

        result = ensure_dev_secret(cwd=str(tmp_path))

        assert result is None                       # no secret minted
        assert "TINA4_SECRET" not in os.environ     # process env untouched
        assert not (tmp_path / ".env.local").exists()  # nothing written

    def test_production_does_not_generate_or_write(self, tmp_path, monkeypatch):
        _clear_secret_env(monkeypatch)
        monkeypatch.setenv("TINA4_DEBUG", "true")
        monkeypatch.setenv("TINA4_ENV", "production")

        result = ensure_dev_secret(cwd=str(tmp_path))

        assert result is None
        assert "TINA4_SECRET" not in os.environ
        assert not (tmp_path / ".env.local").exists()

    def test_non_dev_does_not_generate(self, tmp_path, monkeypatch):
        # TINA4_DEBUG falsy → not dev → no generation even outside CI/prod.
        _clear_secret_env(monkeypatch)
        monkeypatch.setenv("TINA4_DEBUG", "false")

        result = ensure_dev_secret(cwd=str(tmp_path))

        assert result is None
        assert "TINA4_SECRET" not in os.environ
        assert not (tmp_path / ".env.local").exists()


class TestNeverCrashesOnWriteFailure:
    def test_unwritable_env_local_keeps_in_memory_secret(self, tmp_path, monkeypatch):
        _clear_secret_env(monkeypatch)
        monkeypatch.setenv("TINA4_DEBUG", "true")
        # Point cwd at a path that cannot be written (a file, not a dir),
        # so opening <path>/.env.local raises — the bootstrap must NOT crash.
        not_a_dir = tmp_path / "blocker"
        not_a_dir.write_text("x", encoding="utf-8")

        secret = ensure_dev_secret(cwd=str(not_a_dir))

        # In-memory secret kept for this run despite the write failure.
        assert secret is not None
        assert os.environ["TINA4_SECRET"] == secret
