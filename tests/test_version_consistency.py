"""Guard against release-bump drift.

The release process bumps pyproject.toml but has historically left the version
string in CLAUDE.md behind (the AI-facing doc that assistants read as ground
truth), so tools reported an outdated "latest version". This pure-logic test
fails the build if CLAUDE.md's version strings do not match the package version.
No external dependency -- it only reads two files in the repo.
"""
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _package_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return data["project"]["version"]


def test_claude_md_version_matches_pyproject():
    version = _package_version()
    claude = (ROOT / "CLAUDE.md").read_text()

    # Header line: "Version 3.13.72 - ..."
    assert re.search(rf"^Version {re.escape(version)}\b", claude, re.M), (
        f"CLAUDE.md header version is not {version} (bump it with the release)"
    )

    # Every "- Version: X" footer line must equal the package version.
    footers = re.findall(r"^- Version:\s*(\d+\.\d+\.\d+)", claude, re.M)
    assert footers, "CLAUDE.md is missing its '- Version:' footer line"
    stale = sorted({v for v in footers if v != version})
    assert not stale, f"stale CLAUDE.md footer version(s) {stale}, expected {version}"
