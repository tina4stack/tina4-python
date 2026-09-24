"""The real engines a concurrency test can reach, read from the TINA4_TEST_* env.

Shared by the ADR-0074 suites (test_db_concurrency, test_db_async_contract,
test_db_fetch_single_execution). SQLite is always present. Every other engine is
present when its variables are set; an engine that is not configured is not
collected, so ``required_engines_missing()`` turns a missing CI-provisioned engine
into a FAILURE under TINA4_REQUIRE_SERVICES instead of a silently shorter run.
"""
import os

# CI provisions these (see conftest._SERVICE_KEYWORDS). Firebird and ODBC run on
# the lab and are collected there when their variables are set.
PROVISIONED = ("postgres", "mysql", "mssql", "mongodb")


def engines(sqlite_path: str | None = None) -> list[tuple[str, str, str, str]]:
    """``[(name, url, username, password), ...]`` for every configured engine."""
    found = [("sqlite", f"sqlite:///{sqlite_path}" if sqlite_path else "", "", "")]
    env = os.environ.get
    if env("TINA4_TEST_PG_URL"):
        found.append(("postgres", env("TINA4_TEST_PG_URL"),
                      env("TINA4_TEST_PG_USERNAME", ""), env("TINA4_TEST_PG_PASSWORD", "")))
    if env("TINA4_TEST_MYSQL_URL"):
        found.append(("mysql", env("TINA4_TEST_MYSQL_URL"),
                      env("TINA4_TEST_MYSQL_USERNAME", ""), env("TINA4_TEST_MYSQL_PASSWORD", "")))
    if env("TINA4_TEST_MSSQL_URL"):
        found.append(("mssql", env("TINA4_TEST_MSSQL_URL"),
                      env("TINA4_TEST_MSSQL_USERNAME", ""), env("TINA4_TEST_MSSQL_PASSWORD", "")))
    if env("TINA4_TEST_FIREBIRD_URL"):
        found.append(("firebird", env("TINA4_TEST_FIREBIRD_URL"),
                      env("TINA4_TEST_FIREBIRD_USERNAME", "SYSDBA"),
                      env("TINA4_TEST_FIREBIRD_PASSWORD", "masterkey")))
    if env("TINA4_TEST_ODBC_DSN"):
        found.append(("odbc", "odbc:///" + env("TINA4_TEST_ODBC_DSN"), "", ""))
    if env("TINA4_TEST_MONGO_URI"):
        found.append(("mongodb", env("TINA4_TEST_MONGO_URI").rstrip("/") + "/tina4_concurrency", "", ""))
    return found


def names() -> list[str]:
    return [name for name, *_ in engines()]


def required_engines_missing() -> list[str]:
    """CI-provisioned engines absent from this run while TINA4_REQUIRE_SERVICES=1."""
    if os.environ.get("TINA4_REQUIRE_SERVICES", "").strip().lower() not in ("1", "true", "yes"):
        return []
    present = set(names())
    return [name for name in PROVISIONED if name not in present]
