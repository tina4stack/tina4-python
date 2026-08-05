"""Regression suite for the TINA4_REQUIRE_SERVICES skip gate (tests/conftest.py).

THE DEFECT, measured 2026-08-06 on the lab (Ubuntu 24.04.4 LTS x86_64,
Python 3.13.3, live MinIO container tina4-lab-minio on 9100):

``uv sync --extra X`` PRUNES every package outside the named extras, and boto3
was declared in NO extra at all. It happened to be installed ad hoc, so the two
REAL-MinIO tests in tests/test_realtime_files.py were passing -- 9 passed, 0
skipped. Running ``uv sync --extra test`` removed boto3 (plus s3transfer and
jmespath) and the same file reported 7 passed, 2 skipped. The run stayed GREEN
even with TINA4_REQUIRE_SERVICES=1, because the old merged skip reason

    "needs a real MinIO on localhost:9100 and boto3 (real S3, never mocked)"

matched NEITHER a service keyword NOR an unavailable hint in the gate. Live S3
coverage evaporated in silence, which is precisely what this gate exists to
prevent.

THE FIX has two halves, and each is pinned below:
  1. boto3 is declared in the pyproject `test` extra, so a sync installs it.
  2. The gate recognises a missing boto3, so if it ever goes away again the run
     goes RED instead of quietly dropping the coverage.

WHY MinIO ITSELF IS NOT IN THE GATE. MinIO is not provisioned by
.github/workflows/test.yml and has no entry in the shared
tests/fixtures/test_env_contract.json, so -- exactly like Firebird -- an
unreachable-MinIO skip is honest and must stay green. That asymmetry is the
whole reason test_realtime_files.py reports the missing CLIENT and the
unreachable SERVICE as two separate strings: a single merged reason would carry
the "boto3" keyword even when the real cause was an absent MinIO, turning every
MinIO-less CI run red for no reason.

These are pure-function tests over the gate's own predicate and over the
declared pyproject extras. No service, no dependency, no test double.
"""
import tomllib
from pathlib import Path

import pytest

from conftest import _is_provisioned_service_skip, _truthy
from test_realtime_files import BOTO3_MISSING_REASON, MINIO_UNREACHABLE_REASON

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


# ── The gate classifies the two S3 reasons differently ──────────────

class TestS3SkipClassification:
    """The exact strings test_realtime_files.py emits, not copies of them.

    Importing the real constants is the point: a reworded reason that drifts out
    of the gate's vocabulary fails here instead of silently going undetected for
    another few releases.
    """

    def test_missing_boto3_skip_fails_the_gate(self):
        # POSITIVE: boto3 is a DECLARED client, so its absence is always a
        # defect and must turn the run red under TINA4_REQUIRE_SERVICES.
        assert _is_provisioned_service_skip(BOTO3_MISSING_REASON) is True

    def test_unreachable_minio_skip_stays_green(self):
        # NEGATIVE: MinIO is not provisioned in CI and is absent from the shared
        # env contract, so this skip is honest. Adding "minio" to the gate's
        # keywords would fail every CI run and would be caught right here.
        assert _is_provisioned_service_skip(MINIO_UNREACHABLE_REASON) is False

    def test_the_two_reasons_are_never_merged(self):
        # A merged reason carries the boto3 keyword even when MinIO is the real
        # cause. Keeping them distinct is what makes the gate honest, so pin it.
        assert BOTO3_MISSING_REASON != MINIO_UNREACHABLE_REASON
        assert "boto3" not in MINIO_UNREACHABLE_REASON.lower()
        assert "minio" not in BOTO3_MISSING_REASON.lower()

    def test_the_original_merged_reason_was_invisible_to_the_gate(self):
        # The historical string, kept verbatim as the record of the defect: it
        # named a service and a client but used none of the gate's vocabulary,
        # so it was classified as an ordinary skip and the suite reported green.
        # This is why every real-service skip reason must say "not installed" /
        # "not reachable" rather than "needs a ...".
        original = "needs a real MinIO on localhost:9100 and boto3 (real S3, never mocked)"
        assert _is_provisioned_service_skip(original) is False


# ── Genuinely-unprovisioned skips must keep passing ─────────────────

class TestUnprovisionedSkipsStayGreen:
    """Guards the gate against over-broad keywords.

    Adding a short token like "s3" would match "pymssql" nowhere but would make
    future reasons ambiguous; these cases fail the moment the keyword list grows
    teeth it should not have.
    """

    @pytest.mark.parametrize("reason", [
        "Firebird not reachable at localhost:3050",
        "firebird-driver not installed",
        "pyodbc not installed",
        "ODBC driver not available",
    ])
    def test_unprovisioned_service_skip_is_not_a_failure(self, reason):
        assert _is_provisioned_service_skip(reason) is False


class TestProvisionedSkipsAreCaught:
    """The provisioned set must stay caught -- this is the gate's day job."""

    @pytest.mark.parametrize("reason", [
        "PostgreSQL not reachable at localhost:55432",
        "pika not installed",
        "pymemcache not installed",
        "confluent-kafka not installed",
        "MongoDB not reachable at localhost:27017",
        "GreenMail SMTP not reachable at localhost:3025",
        "boto3 not installed",
    ])
    def test_provisioned_service_skip_is_a_failure(self, reason):
        assert _is_provisioned_service_skip(reason) is True

    def test_a_skip_with_no_service_at_all_is_not_a_failure(self):
        # NEGATIVE: an ordinary conditional skip must never be upgraded.
        assert _is_provisioned_service_skip("only runs on Windows") is False
        assert _is_provisioned_service_skip("") is False
        assert _is_provisioned_service_skip(None) is False

    def test_a_service_named_without_an_unavailable_hint_is_not_a_failure(self):
        # Both halves are required: naming a service is not enough, or a test
        # that merely mentions Postgres in a skip reason would fail the run.
        assert _is_provisioned_service_skip("postgres tests are slow here") is False


# ── boto3 is actually declared, so a sync installs it ───────────────

class TestBoto3IsDeclared:
    """The declaration half of the fix.

    The gate can only fire on a host that was SUPPOSED to have boto3; these
    assert the pyproject actually says so, which is what makes
    `uv sync --extra test` reproducible instead of relying on an ad-hoc install.
    """

    def test_boto3_is_declared_in_the_test_extra(self):
        # POSITIVE: this is the line whose absence caused the defect.
        assert _declares("test", "boto3"), (
            "boto3 must be in the `test` extra: `uv sync --extra test` prunes "
            "anything outside the named extras, so an undeclared boto3 is "
            "silently uninstalled and the live-MinIO S3 tests stop running."
        )

    def test_boto3_is_declared_in_the_s3_extra(self):
        # POSITIVE: S3Storage imports boto3 lazily, so applications need a
        # declared install path too -- every other optional backend has one.
        assert _declares("s3", "boto3")

    def test_the_test_extra_still_carries_every_other_live_client(self):
        # NEGATIVE guard against a careless edit dropping a client while adding
        # one. Each of these was itself an undeclared-dependency incident.
        for package in ("psycopg2-binary", "mysql-connector-python", "pymssql",
                        "firebird-driver", "pymongo", "pyodbc", "redis",
                        "pymemcache", "confluent-kafka", "pika"):
            assert _declares("test", package), f"{package} dropped from the test extra"


def test_the_gate_is_inert_unless_the_env_var_is_set():
    # The gate must not fire on a developer laptop that never opted in.
    assert _truthy("1") is True
    assert _truthy("true") is True
    assert _truthy("") is False
    assert _truthy(None) is False
    assert _truthy("0") is False
