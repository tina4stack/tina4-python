"""
Benchmark: OLD tina4 Database.fetch() vs NEW Database.fetch()

Compares the actual old two-query pagination (from git commit b20a635)
against the new single-query window function approach, using the real
tina4_python Database wrapper on all available engines.

The OLD fetch logic is extracted from the last committed version and
monkey-patched onto the Database instance, so both approaches use
the exact same connection, data, and framework overhead.

Run with:
  .venv/bin/python benchmarks/src/bench_pagination.py
"""

import re
import time
import random
import string
import os
import types

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
NUM_ROWS = 10_000
ITERATIONS = 50
LIMIT = 20  # rows per page

SQLITE_DB = os.path.join(os.path.dirname(__file__), "_bench_pagination.db")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def random_string(length=12):
    return "".join(random.choices(string.ascii_lowercase, k=length))


def random_email():
    return f"{random_string(8)}@{random_string(5)}.com"


# ---------------------------------------------------------------------------
# OLD fetch — extracted verbatim from git commit b20a635
# This is the two-query approach that was in production before our changes.
# ---------------------------------------------------------------------------
def old_fetch(self, sql, params=None, limit=10, skip=0, search=None, search_columns=None):
    """OLD two-query fetch from git b20a635 — monkey-patched onto db instance."""
    from tina4_python.DatabaseResult import DatabaseResult
    from tina4_python.DatabaseTypes import FIREBIRD, MSSQL, MYSQL, SQLITE, POSTGRES
    from tina4_python.Debug import Debug

    if params is None:
        params = []
    if isinstance(params, list):
        params = params.copy()
    else:
        params = list(params)

    self.check_connected()

    final_sql = sql
    final_params = params

    if search and search.strip():
        search = search.strip()
        cols = search_columns or getattr(self, "columns", None)
        if not cols:
            m = re.search(r"SELECT\s+([\s\S]*?)\s+FROM", final_sql, re.I)
            if m:
                raw = re.split(r',\s*(?=[a-zA-Z_`"\[\]])', m.group(1))
                cols = []
                for c in raw:
                    name = c.strip().split()[-1].split(".")[-1]
                    name = re.sub(r'^[`"\[(].*[`"\])]$', '', name).strip('`"[]')
                    if name and name != "*":
                        cols.append(name)
        if cols:
            like_op = "ILIKE" if self.database_engine == POSTGRES else "LIKE"
            conditions = []
            for col in cols:
                col_name = f'"{col}"' if " " not in col else col
                conditions.append(f"cast({col_name} as varchar(1000)) {like_op} ?")
                final_params.append(f"%{search}%")
            where_clause = " WHERE (" + " OR ".join(conditions) + ")"
            final_sql = sql + where_clause

    # --- TWO-QUERY APPROACH ---
    # Query 1: COUNT
    count_sql = f"SELECT COUNT(*) AS count_records FROM ({final_sql}) AS t"
    counter = self.dba.cursor()
    try:
        counter.execute(self.parse_place_holders(count_sql), final_params)
        total = counter.fetchone()[0]
    except Exception as e:
        Debug.error("COUNT ERROR", count_sql, final_params, str(e))
        try:
            self.dba.rollback()
        except Exception:
            pass
        total = 0
    finally:
        counter.close()

    # Query 2: PAGINATED DATA
    if self.database_engine == FIREBIRD:
        final_sql = f"SELECT FIRST {limit} SKIP {skip} * FROM ({final_sql}) AS t"
    elif self.database_engine == MSSQL:
        inner = final_sql.strip()
        order_by_match = re.search(r"(?i)\border\s+by\s+.+?$", inner, re.DOTALL)
        has_order_by = order_by_match is not None
        if has_order_by:
            inner_clean = re.sub(r"(?i)\s+order\s+by\s+.+?$", "", inner, flags=re.DOTALL).strip()
            order_by_part = order_by_match.group(0)
        else:
            inner_clean = inner
            order_by_part = "ORDER BY (SELECT NULL)"
        final_sql = f"SELECT * FROM ({inner_clean}) AS t {order_by_part} OFFSET {skip} ROWS FETCH NEXT {limit} ROWS ONLY"
    else:
        final_sql = f"SELECT * FROM ({final_sql}) AS t LIMIT {limit} OFFSET {skip}"

    final_sql = self.parse_place_holders(final_sql)

    cursor = self.dba.cursor()
    try:
        cursor.execute(final_sql, final_params)
        return self.get_database_result(cursor, total, limit, skip, final_sql)
    except Exception as e:
        Debug.error("FETCH ERROR", final_sql, final_params, str(e))
        try:
            self.dba.rollback()
        except Exception:
            pass
        return DatabaseResult(None, [], str(e))
    finally:
        cursor.close()


# ---------------------------------------------------------------------------
# Engine connections
# ---------------------------------------------------------------------------
def _connect_sqlite():
    from tina4_python.Database import Database
    if os.path.exists(SQLITE_DB):
        os.remove(SQLITE_DB)
    return Database(f"sqlite3:{SQLITE_DB}", "", ""), "SQLite"


def _connect_postgres():
    try:
        from tina4_python.Database import Database
        db = Database("psycopg2:localhost/5437:postgres", "postgres", "YourStrong!Passw0rd")
        return (db, "PostgreSQL") if db.dba else (None, "PostgreSQL")
    except Exception:
        return None, "PostgreSQL"


def _connect_mysql():
    try:
        from tina4_python.Database import Database
        db = Database("mysql.connector:localhost/3306:testdb", "root", "masterkey")
        return (db, "MySQL") if db.dba else (None, "MySQL")
    except Exception:
        return None, "MySQL"


def _connect_firebird():
    try:
        from tina4_python.Database import Database
        db = Database(
            "firebird.driver:localhost/33053:/var/lib/firebird/data/ACCOUNTING.FDB",
            "sysdba", "masterkey",
        )
        return (db, "Firebird") if db.dba else (None, "Firebird")
    except Exception:
        return None, "Firebird"


def _connect_mssql():
    try:
        from tina4_python.Database import Database
        db = Database("pymssql:localhost/1433:master", "sa", "Master1234")
        return (db, "MSSQL") if db.dba else (None, "MSSQL")
    except Exception:
        return None, "MSSQL"


ENGINE_CONNECTORS = [
    _connect_sqlite,
    _connect_postgres,
    _connect_mysql,
    _connect_firebird,
    _connect_mssql,
]


# ---------------------------------------------------------------------------
# Data seeding
# ---------------------------------------------------------------------------
def setup_data(db):
    from tina4_python.DatabaseTypes import MSSQL, FIREBIRD

    for tbl in ["orders", "users"]:
        try:
            db.execute(f"DROP TABLE {tbl}")
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

    if db.database_engine == FIREBIRD:
        db.execute("""
            CREATE TABLE users (
                id INTEGER NOT NULL PRIMARY KEY, name VARCHAR(100) NOT NULL,
                email VARCHAR(200) NOT NULL, age INTEGER NOT NULL,
                city VARCHAR(100) NOT NULL, active INTEGER DEFAULT 1 NOT NULL,
                created_at VARCHAR(20) NOT NULL)
        """)
        db.execute("""
            CREATE TABLE orders (
                id INTEGER NOT NULL PRIMARY KEY, user_id INTEGER NOT NULL,
                amount DOUBLE PRECISION NOT NULL, status VARCHAR(50) NOT NULL,
                created_at VARCHAR(20) NOT NULL)
        """)
    elif db.database_engine == MSSQL:
        db.execute("""
            CREATE TABLE users (
                id INTEGER NOT NULL PRIMARY KEY, name VARCHAR(100) NOT NULL,
                email VARCHAR(200) NOT NULL, age INTEGER NOT NULL,
                city VARCHAR(100) NOT NULL, active INTEGER NOT NULL DEFAULT 1,
                created_at VARCHAR(20) NOT NULL)
        """)
        db.execute("""
            CREATE TABLE orders (
                id INTEGER NOT NULL PRIMARY KEY, user_id INTEGER NOT NULL,
                amount REAL NOT NULL, status VARCHAR(50) NOT NULL,
                created_at VARCHAR(20) NOT NULL)
        """)
    else:
        db.execute("""
            CREATE TABLE users (
                id INTEGER NOT NULL PRIMARY KEY, name VARCHAR(100) NOT NULL,
                email VARCHAR(200) NOT NULL, age INTEGER NOT NULL,
                city VARCHAR(100) NOT NULL, active INTEGER NOT NULL DEFAULT 1,
                created_at VARCHAR(20) NOT NULL)
        """)
        db.execute("""
            CREATE TABLE orders (
                id INTEGER NOT NULL PRIMARY KEY, user_id INTEGER NOT NULL,
                amount REAL NOT NULL, status VARCHAR(50) NOT NULL,
                created_at VARCHAR(20) NOT NULL)
        """)
    db.commit()

    cities = ["New York", "London", "Tokyo", "Paris", "Berlin",
              "Sydney", "Toronto", "Mumbai", "Sao Paulo", "Cairo"]
    statuses = ["pending", "shipped", "delivered", "cancelled"]

    random.seed(42)
    order_id = 1

    for i in range(1, NUM_ROWS + 1):
        db.execute(
            "INSERT INTO users (id, name, email, age, city, active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [i, random_string(10), random_email(), random.randint(18, 80),
             random.choice(cities), random.choice([0, 1]),
             f"2024-{random.randint(1,12):02d}-{random.randint(1,28):02d}"],
        )
        for _ in range(random.randint(1, 5)):
            db.execute(
                "INSERT INTO orders (id, user_id, amount, status, created_at) VALUES (?, ?, ?, ?, ?)",
                [order_id, i, round(random.uniform(5.0, 500.0), 2),
                 random.choice(statuses),
                 f"2024-{random.randint(1,12):02d}-{random.randint(1,28):02d}"],
            )
            order_id += 1
        if i % 500 == 0:
            db.commit()

    db.commit()
    print(f"    Seeded {NUM_ROWS} users, {order_id - 1} orders")


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------
def bench(db, name, sql, pages):
    results = []
    # Save the NEW fetch method
    new_fetch = db.fetch

    for page in pages:
        skip = (page - 1) * LIMIT
        label = f"{name} (p{page})"

        # Warm up both
        try:
            db.fetch = types.MethodType(old_fetch, db)
            db.fetch(sql, limit=LIMIT, skip=skip)
            db.fetch = new_fetch
            db.fetch(sql, limit=LIMIT, skip=skip)
        except Exception as e:
            print(f"    SKIP {label}: {e}")
            db.fetch = new_fetch
            continue

        # OLD approach (two queries)
        db.fetch = types.MethodType(old_fetch, db)
        t0 = time.perf_counter()
        for _ in range(ITERATIONS):
            result_old = db.fetch(sql, limit=LIMIT, skip=skip)
        old_ms = (time.perf_counter() - t0) / ITERATIONS * 1000

        # NEW approach (single query)
        db.fetch = new_fetch
        t0 = time.perf_counter()
        for _ in range(ITERATIONS):
            result_new = db.fetch(sql, limit=LIMIT, skip=skip)
        new_ms = (time.perf_counter() - t0) / ITERATIONS * 1000

        # Verify correctness — both must return same total and same number of rows
        old_total = result_old.total_count
        new_total = result_new.total_count
        old_rows = result_old.count
        new_rows = result_new.count

        correctness = "OK" if (old_total == new_total and old_rows == new_rows) else f"MISMATCH old={old_total}/{old_rows} new={new_total}/{new_rows}"

        speedup = old_ms / new_ms if new_ms > 0 else float("inf")
        improvement = (1 - new_ms / old_ms) * 100 if old_ms > 0 else 0

        results.append((label, old_ms, new_ms, speedup, improvement, correctness))

    # Restore
    db.fetch = new_fetch
    return results


def print_results(engine_name, all_results):
    if not all_results:
        return None

    print()
    hdr = f"  {engine_name} Results"
    print(f"  {'=' * 100}")
    print(hdr)
    print(f"  {'-' * 100}")
    print(
        f"  {'Scenario':<30} {'Old 2Q (ms)':>12} {'New 1Q (ms)':>12} {'Speedup':>10} {'Change':>12} {'Correct':>10}"
    )
    print(f"  {'-' * 100}")

    for label, old_ms, new_ms, speedup, improvement, correctness in all_results:
        sign = "+" if improvement > 0 else ""
        print(
            f"  {label:<30} {old_ms:>12.3f} {new_ms:>12.3f} {speedup:>9.2f}x {sign}{improvement:>10.1f}% {correctness:>10}"
        )

    print(f"  {'-' * 100}")

    avg_old = sum(r[1] for r in all_results) / len(all_results)
    avg_new = sum(r[2] for r in all_results) / len(all_results)
    avg_speedup = avg_old / avg_new if avg_new > 0 else float("inf")
    avg_improvement = (1 - avg_new / avg_old) * 100 if avg_old > 0 else 0
    sign = "+" if avg_improvement > 0 else ""

    all_correct = all(r[5] == "OK" for r in all_results)
    corr_str = "ALL OK" if all_correct else "ISSUES"

    print(
        f"  {'AVERAGE':<30} {avg_old:>12.3f} {avg_new:>12.3f} {avg_speedup:>9.2f}x {sign}{avg_improvement:>10.1f}% {corr_str:>10}"
    )
    print(f"  {'=' * 100}")

    return engine_name, avg_old, avg_new, avg_speedup, avg_improvement, all_correct


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------
SCENARIOS = [
    ("Simple SELECT *", "SELECT * FROM users"),
    ("WHERE clause", "SELECT * FROM users WHERE active = 1 AND age > 30"),
    ("JOIN", "SELECT u.id, u.name, o.amount, o.status FROM users u INNER JOIN orders o ON u.id = o.user_id"),
    ("ORDER BY", "SELECT * FROM users ORDER BY age DESC, name ASC"),
]

PAGES = [1, 50, 100]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print()
    print("=" * 104)
    print("  PAGINATION BENCHMARK: Old tina4 fetch (2 queries) vs New tina4 fetch (1 query)")
    print("=" * 104)
    print(f"  Data: {NUM_ROWS} users + ~30k orders  |  Page size: {LIMIT}  |  {ITERATIONS} iterations/measurement")
    print(f"  Both approaches use the real tina4_python Database wrapper on the same connection.")
    print()

    summaries = []

    for connector in ENGINE_CONNECTORS:
        db, engine_name = connector()
        if db is None:
            print(f"  [{engine_name}] Not available — skipping")
            continue

        print(f"  [{engine_name}] Connected. Seeding {NUM_ROWS} rows...")
        try:
            setup_data(db)
        except Exception as e:
            print(f"    FAILED to seed: {e}")
            continue

        all_results = []
        for scenario_name, sql in SCENARIOS:
            all_results += bench(db, scenario_name, sql, PAGES)

        summary = print_results(engine_name, all_results)
        if summary:
            summaries.append(summary)

        # Cleanup
        for tbl in ["orders", "users"]:
            try:
                db.execute(f"DROP TABLE {tbl}")
                db.commit()
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass

    # Cross-engine summary
    if summaries:
        print()
        print("=" * 104)
        print("  CROSS-ENGINE SUMMARY")
        print(f"  {'-' * 80}")
        print(f"  {'Engine':<16} {'Avg Old (ms)':>14} {'Avg New (ms)':>14} {'Speedup':>10} {'Change':>14} {'Correct':>10}")
        print(f"  {'-' * 80}")
        for engine_name, avg_old, avg_new, avg_speedup, avg_improvement, all_correct in summaries:
            sign = "+" if avg_improvement > 0 else ""
            corr_str = "ALL OK" if all_correct else "ISSUES"
            print(
                f"  {engine_name:<16} {avg_old:>14.3f} {avg_new:>14.3f} {avg_speedup:>9.2f}x {sign}{avg_improvement:>12.1f}% {corr_str:>10}"
            )
        print(f"  {'=' * 80}")

    # Cleanup SQLite
    if os.path.exists(SQLITE_DB):
        os.remove(SQLITE_DB)

    print()
    print("  NOTE: On in-process databases (SQLite), the new approach may be slower because")
    print("  there's no network round-trip to eliminate. The win is on client-server databases")
    print("  (PostgreSQL, MySQL, Firebird, MSSQL) where each query incurs network overhead.")
    print()


if __name__ == "__main__":
    main()
