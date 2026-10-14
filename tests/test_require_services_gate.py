# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The TINA4_REQUIRE_SERVICES skip gate (tests/conftest.py), tested for real.

THE RULE (ADR-0069 addendum F, identical in all four frameworks). Under
TINA4_REQUIRE_SERVICES=1 a skip passes only when its reason carries a
``[needs:X]`` tag AND X is excusable in this run: an optional engine only while
its coordinate env var is unset, an always-provisioned service never, any other
X (a platform exclusion) always. An untagged skip fails. With the gate off, a
skip is a skip.

WHY. The gate used to match phrases: a service keyword AND an "unavailable"
hint. Every skip worded outside those lists skipped green. MEASURED 2026-08-06
on the lab: the merged live-S3 reason "needs a real MinIO on localhost:9100 and
boto3 (real S3, never mocked)" matched neither list, so removing boto3 silently
turned two real-MinIO tests into skips under a green run. Firebird, ODBC, MinIO
and the graph engines were deliberately left out of the keywords, so their
skips were green by design. An explicit tag closes all of those at once: a
skip has to say what it needs, and the gate decides from the run's own env.

S3Storage is now zero-dependency (Tina4's own stdlib SigV4 client, no boto3), so
the live-S3 skip has a single cause — MinIO/Garage unreachable — and boto3 is
gone from every extra; the regression guards for that are pinned below.

The gate cases run a REAL pytest in a child process against a throwaway project
whose conftest.py is a byte-for-byte copy of tests/conftest.py, so the gate
under test is the one the suite uses. No doubles.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest

from conftest import _skip_is_excused, _truthy
from test_realtime_files import MINIO_UNREACHABLE_REASON

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _extras() -> dict:
    with open(PYPROJECT, "rb") as handle:
        return tomllib.load(handle)["project"]["optional-dependencies"]


def _declares(extra: str, package: str) -> bool:
    """True when `extra` declares `package`, ignoring the version specifier."""
    return any(
        spec.split(">")[0].split("<")[0].split("=")[0].split("[")[0].strip() == package
        for spec in _extras().get(extra, [])
    )


# ── The predicate ──────────────────────────────────────────────────

NO_COORDINATES: dict = {}
ALL_COORDINATES = {
    "TINA4_TEST_FIREBIRD_URL": "firebird://localhost/db",
    "TINA4_TEST_PG_URL": "postgres://localhost/db",
    "TINA4_TEST_POSTGIS_URL": "postgres://localhost:55433/db",
    "TINA4_TEST_MYSQL_URL": "mysql://localhost/db",
    "TINA4_TEST_MSSQL_URL": "mssql://localhost/db",
    "TINA4_TEST_OIDC_ISSUER": "http://localhost/realm",
    "TINA4_TEST_NEO4J_URL": "bolt://localhost:7687",
}


class TestSkipPredicate:
    @pytest.mark.parametrize("reason", [
        "[needs:os=posix] fork is POSIX-only",
        "four-slash form is POSIX-shaped [needs:os=posix]",
        "[needs:no-dac-override] root writes through a 0400 file",
        "[needs:runtime=ipv6-loopback] no ::1 here",
    ])
    def test_a_platform_tag_is_always_excused(self, reason):
        assert _skip_is_excused(reason, NO_COORDINATES) is True
        assert _skip_is_excused(reason, ALL_COORDINATES) is True

    @pytest.mark.parametrize("tag, coordinate", [
        ("firebird", "TINA4_TEST_FIREBIRD_URL"),
        ("postgres", "TINA4_TEST_PG_URL"),
        ("postgis", "TINA4_TEST_POSTGIS_URL"),
        ("mysql", "TINA4_TEST_MYSQL_URL"),
        ("mssql", "TINA4_TEST_MSSQL_URL"),
        ("oidc", "TINA4_TEST_OIDC_ISSUER"),
        ("neo4j", "TINA4_TEST_NEO4J_URL"),
    ])
    def test_an_optional_engine_is_excused_only_while_its_coordinate_is_unset(self, tag, coordinate):
        reason = f"[needs:{tag}] not reachable"
        assert _skip_is_excused(reason, NO_COORDINATES) is True
        assert _skip_is_excused(reason, {coordinate: "set"}) is False
        # An empty value counts as unset.
        assert _skip_is_excused(reason, {coordinate: "  "}) is True

    @pytest.mark.parametrize("tag", [
        "mongo", "redis", "valkey", "memcached", "rabbitmq", "kafka", "mqtt", "smtp", "imap", "s3",
    ])
    def test_an_always_provisioned_service_is_never_excused(self, tag):
        assert _skip_is_excused(f"[needs:{tag}] down", NO_COORDINATES) is False

    @pytest.mark.parametrize("reason", [
        MINIO_UNREACHABLE_REASON,
        # The historical merged reason that the old phrase matcher missed.
        "needs a real MinIO on localhost:9100 and boto3 (real S3, never mocked)",
        "Firebird not reachable at localhost:3050",
        "no reachable MongoDB at mongodb://localhost:27017",
        "only runs on Windows",
        "[needs:] empty tag",
        "[needs: spaced] tag with a space",
        "",
        None,
    ])
    def test_an_untagged_reason_is_never_excused(self, reason):
        assert _skip_is_excused(reason, NO_COORDINATES) is False

    def test_every_tag_on_a_reason_must_be_excused(self):
        assert _skip_is_excused("[needs:os=posix] [needs:mongo]", NO_COORDINATES) is False


# ── boto3 is gone: S3Storage is zero-dependency ─────────────────────

class TestNoBoto3:
    """S3Storage now talks to S3 through Tina4's own stdlib SigV4 client, so
    boto3 must not reappear in any extra (it would drag botocore + urllib3 back
    into the tree with it). These are the regression guards for that win.
    """

    def test_boto3_is_not_in_the_test_extra(self):
        assert not _declares("test", "boto3"), (
            "boto3 was removed from the `test` extra when S3Storage went "
            "zero-dependency; re-adding it drags botocore + urllib3 back."
        )

    def test_boto3_is_not_in_the_s3_extra(self):
        assert not _declares("s3", "boto3"), (
            "the `s3` extra is zero-dependency now — S3Storage needs no driver."
        )

    def test_no_shipped_doc_says_s3_needs_boto3(self):
        # CLAUDE.md and the developer skill (every tree) are what a reader or an
        # agent installs from; telling them S3 needs boto3 sends them to install
        # a driver the code never imports.
        root = PYPROJECT.parent
        docs = [root / "CLAUDE.md", *sorted(root.glob(".*/skills/tina4-developer-python/**/*.md"))]
        claims = ("needs boto3", "boto3 missing", "via boto3", "boto3 is required")
        stale = [f"{doc.relative_to(root)}:{n}" for doc in docs
                 for n, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1)
                 if any(claim in line for claim in claims)]
        assert len(docs) > 3, f"found only {docs}"
        assert not stale, f"docs still say S3 needs boto3: {stale}"

    def test_the_test_extra_still_carries_every_other_live_client(self):
        # NEGATIVE guard against a careless edit dropping a client while adding
        # one. Each of these was itself an undeclared-dependency incident.
        for package in ("psycopg2-binary", "mysql-connector-python", "pymssql",
                        "firebird-driver", "pymongo", "pyodbc", "redis",
                        "pymemcache", "confluent-kafka", "pika"):
            assert _declares("test", package), f"{package} dropped from the test extra"


def test_the_env_var_is_read_as_a_boolean():
    # The gate must not fire on a developer laptop that never opted in.
    assert _truthy("1") is True
    assert _truthy("true") is True
    assert _truthy("") is False
    assert _truthy(None) is False
    assert _truthy("0") is False


# ── The gate itself, in a real pytest run ───────────────────────────

CONFTEST = Path(__file__).with_name("conftest.py")

SAMPLE_TESTS = '''
import pytest


def test_passes():
    assert True


def test_untagged_skip():
    pytest.skip("some service is down")


@pytest.mark.skipif(True, reason="phrased without any known keyword")
def test_untagged_skipif():
    pass


def test_platform_skip():
    pytest.skip("[needs:os=posix] this platform has no fork")


@pytest.mark.skipif(True, reason="[needs:os=posix] Windows uses drive letters")
def test_platform_skipif():
    pass


def test_optional_engine_skip():
    pytest.skip("[needs:firebird] Firebird not reachable")


def test_always_service_skip():
    pytest.skip("[needs:mongo] MongoDB not reachable")


@pytest.mark.xfail(reason="documented known failure", strict=True)
def test_expected_failure():
    assert False
'''

MODULE_LEVEL_UNTAGGED = '''
import pytest
pytest.skip("module service is down", allow_module_level=True)


def test_never_runs():
    pass
'''

MODULE_LEVEL_PLATFORM = '''
import pytest
pytest.skip("[needs:os=posix] no lsof here", allow_module_level=True)


def test_never_runs():
    pass
'''


def _run(tmp_path: Path, gate_on: bool, firebird_url: str = "") -> dict[str, str]:
    """Run the sample project; map each test (or skipped module) to its outcome."""
    project = tmp_path / "project"
    project.mkdir()
    shutil.copyfile(CONFTEST, project / "conftest.py")
    (project / "test_sample.py").write_text(SAMPLE_TESTS)
    (project / "test_module_untagged.py").write_text(MODULE_LEVEL_UNTAGGED)
    (project / "test_module_platform.py").write_text(MODULE_LEVEL_PLATFORM)
    report = project / "report.xml"

    env = {**os.environ, "TINA4_NO_BROWSER": "true", "TINA4_TEST_FIREBIRD_URL": firebird_url}
    env.pop("TINA4_REQUIRE_SERVICES", None)
    if gate_on:
        env["TINA4_REQUIRE_SERVICES"] = "1"
    # Give the child pytest its OWN tmp base. Without this it shares the parent
    # run's $TMPDIR/pytest-of-<user>, and the child's startup retention cleanup
    # can delete the PARENT's active numbered dir - which cascades every later
    # tmp_path/tmp_path_factory test in the parent into FileNotFoundError.
    child_tmp = tempfile.mkdtemp(prefix="tina4-gate-pytmp-")
    env["TMPDIR"] = env["TMP"] = env["TEMP"] = child_tmp
    try:
        subprocess.run(
            [
                sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
                "--rootdir", str(project), f"--junitxml={report}", str(project),
            ],
            cwd=project, env=env, capture_output=True, text=True, timeout=120,
        )
    finally:
        shutil.rmtree(child_tmp, ignore_errors=True)

    outcomes = {}
    for case in ElementTree.parse(report).getroot().iter("testcase"):
        if case.find("failure") is not None:
            outcome = "failed"
        elif case.find("error") is not None:
            # A skipif fires in setup and a module skip at collection; the
            # gate's failure is reported as an error there.
            outcome = "failed"
        elif case.find("skipped") is not None:
            skipped = case.find("skipped")
            outcome = "xfailed" if skipped.get("type") == "pytest.xfail" else "skipped"
        else:
            outcome = "passed"
        # A module skipped at collection is reported under the module's name.
        outcomes[case.get("name")] = outcome
    return outcomes


@pytest.fixture(scope="module")
def gate_on(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("gate_on"), gate_on=True)


@pytest.fixture(scope="module")
def gate_on_with_firebird_promised(tmp_path_factory):
    return _run(
        tmp_path_factory.mktemp("gate_fb"), gate_on=True,
        firebird_url="firebird://SYSDBA:masterkey@localhost:3050//tmp/x.fdb",
    )


@pytest.fixture(scope="module")
def gate_off(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("gate_off"), gate_on=False)


def test_an_untagged_skip_fails_under_the_gate(gate_on):
    assert gate_on["test_untagged_skip"] == "failed", gate_on
    assert gate_on["test_untagged_skipif"] == "failed", gate_on
    assert gate_on["test_module_untagged"] == "failed", gate_on


def test_a_platform_tag_is_excused_under_the_gate(gate_on):
    assert gate_on["test_platform_skip"] == "skipped", gate_on
    assert gate_on["test_platform_skipif"] == "skipped", gate_on
    assert gate_on["test_module_platform"] == "skipped", gate_on


def test_an_optional_engine_is_excused_only_while_its_coordinate_is_unset(
    gate_on, gate_on_with_firebird_promised,
):
    assert gate_on["test_optional_engine_skip"] == "skipped", gate_on
    assert gate_on_with_firebird_promised["test_optional_engine_skip"] == "failed", (
        gate_on_with_firebird_promised
    )


def test_an_always_provisioned_service_is_never_excused(gate_on):
    assert gate_on["test_always_service_skip"] == "failed", gate_on


def test_the_gate_leaves_passes_and_xfails_alone(gate_on):
    assert gate_on["test_passes"] == "passed", gate_on
    assert gate_on["test_expected_failure"] == "xfailed", gate_on


def test_gate_off_keeps_the_old_skip_behaviour(gate_off):
    for name in (
        "test_untagged_skip", "test_untagged_skipif", "test_platform_skip",
        "test_platform_skipif", "test_optional_engine_skip", "test_always_service_skip",
        "test_module_untagged", "test_module_platform",
    ):
        assert gate_off[name] == "skipped", (name, gate_off)
    assert gate_off["test_passes"] == "passed", gate_off
    assert gate_off["test_expected_failure"] == "xfailed", gate_off
