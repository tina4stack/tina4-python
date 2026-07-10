"""Real tests for the corrected `build` CLI command (Phase 3, Python master).

`build` now produces the deployable Docker image (the artifact a Tina4 app
ships), not a Python library package. These tests drive the REAL `_build`
handler:

  * the fail-loud guards are asserted with a real filesystem and a real,
    genuinely-empty PATH (so `shutil.which("docker")` really returns None — no
    mock);
  * when a real Docker daemon is available, a real `docker build` of a
    network-free `FROM scratch` image is run and the resulting image is
    inspected in the daemon, then cleaned up.
"""
import shutil
import subprocess

import pytest

from tina4_python.cli import _build


def _docker_ready() -> bool:
    """True only when a real docker daemon is reachable (else the real-build
    test is skipped rather than flaking on a missing binary/daemon)."""
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(
            ["docker", "info"], capture_output=True, timeout=15
        ).returncode == 0
    except Exception:  # noqa: BLE001
        return False


DOCKER_READY = _docker_ready()


class TestBuildGuards:
    def test_no_dockerfile_fails_loud(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc:
            _build([])
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "No Dockerfile" in out
        assert "tina4 deploy docker" in out  # actionable guidance, not lib packaging

    def test_dockerfile_present_but_docker_absent_fails_loud(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
        # Real 'docker missing': a genuinely empty PATH makes shutil.which return
        # None. No mock — the environment really has no docker on PATH.
        empty = tmp_path / "emptybin"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        with pytest.raises(SystemExit) as exc:
            _build([])
        assert exc.value.code == 1
        assert "docker" in capsys.readouterr().out.lower()

    def test_custom_file_flag_missing_fails_loud(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc:
            _build(["--file", "docker/prod/Dockerfile"])
        assert exc.value.code == 1
        assert "docker/prod/Dockerfile" in capsys.readouterr().out


@pytest.mark.skipif(not DOCKER_READY, reason="docker daemon not available")
class TestBuildRealImage:
    def test_builds_scratch_image_for_real(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        # FROM scratch needs no registry pull → a real, offline docker build.
        (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
        tag = "tina4-build-test:latest"
        try:
            _build(["--tag", tag])  # must NOT raise SystemExit on success
            out = capsys.readouterr().out
            assert f"Built image {tag}" in out
            # The real artifact exists in the docker daemon.
            inspect = subprocess.run(
                ["docker", "image", "inspect", tag], capture_output=True, text=True
            )
            assert inspect.returncode == 0
        finally:
            subprocess.run(
                ["docker", "image", "rm", "-f", tag], capture_output=True, text=True
            )
