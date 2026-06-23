# Tina4 v3 test configuration

import os

import pytest

# Provisioned real services (and their client libraries). CI stands all of these
# up, so an integration test should never skip in CI. MySQL / MSSQL / Firebird are
# deliberately NOT in this list -- they are not provisioned, so their skips stay
# green.
_SERVICE_KEYWORDS = (
    "postgres", "postgresql", "psycopg2",
    "redis", "valkey", "memcached",
    "mongo",            # also matches "pymongo"
    "rabbit", "amqp",
    "kafka",            # also matches "rdkafka" / "confluent-kafka"
)
_UNAVAILABLE_HINTS = (
    "not reachable", "unreachable", "not running", "not set",
    "not installed", "could not connect", "not available", "refused",
)


def _truthy(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _require_services():
    return _truthy(os.environ.get("TINA4_REQUIRE_SERVICES"))


def _is_provisioned_service_skip(reason):
    low = (reason or "").lower()
    return any(k in low for k in _SERVICE_KEYWORDS) and any(h in low for h in _UNAVAILABLE_HINTS)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """When TINA4_REQUIRE_SERVICES is set, turn a skip caused by a PROVISIONED
    service being unavailable into a hard FAILURE.

    CI provisions PostgreSQL, Redis, Valkey, Memcached, MongoDB, RabbitMQ, and
    Kafka and sets every TINA4_TEST_* URL, so these integration tests must run.
    A skip that names one of those services (or its client library) means the
    service or driver silently went missing -- the exact gap that let the
    migration and queue bugs ship green. MySQL / MSSQL / Firebird are not
    provisioned, so their skips never match these keywords and stay green.
    """
    outcome = yield
    report = outcome.get_result()
    if not _require_services() or not report.skipped:
        return
    try:
        reason = report.longrepr[2] if isinstance(report.longrepr, tuple) else str(report.longrepr)
    except Exception:
        reason = str(getattr(report, "longrepr", ""))
    if _is_provisioned_service_skip(reason):
        report.outcome = "failed"
        report.longrepr = (
            "TINA4_REQUIRE_SERVICES is set, but this real-service test SKIPPED "
            "because a provisioned service or client library is missing:\n  "
            + reason.strip()
            + "\nProvision the service / install the client, or unset TINA4_REQUIRE_SERVICES."
        )
