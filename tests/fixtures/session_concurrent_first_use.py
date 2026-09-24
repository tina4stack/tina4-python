"""ONE worker in the concurrent first-use race driven by
tests/test_session_database_engines.py::test_concurrent_first_use_is_safe_on_every_engine.

A separate PROCESS on purpose: the property under test is what happens when
several processes of one app use the database session backend for the first
time at the same instant. Nothing here is a double - the real handler, the real
Database, the real engine.

It connects BEFORE the barrier (the race is in _ensure_table, not in connection
setup) and then spins to a shared wall-clock instant.

argv[1] float  the instant every worker starts at (time.time())
argv[2] str    the session id this worker writes

Environment (not TINA4_*, so nothing here is mistaken for a framework setting):
    T4_RACE_URL / T4_RACE_USERNAME / T4_RACE_PASSWORD
    T4_RACE_HOLD_NAMED_LOCK   MySQL only - hold a GET_LOCK across the first use

Exit codes: 0 success, 1 the first use failed, 2 could not connect.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tina4_python.database import Database  # noqa: E402
from tina4_python.session import DatabaseSessionHandler  # noqa: E402

start_at = float(sys.argv[1])
session_id = sys.argv[2]

try:
    database = Database(
        os.environ["T4_RACE_URL"],
        os.environ.get("T4_RACE_USERNAME") or None,
        os.environ.get("T4_RACE_PASSWORD") or None,
    )
    handler = DatabaseSessionHandler(database)
    # MySQL backs the loser of the metadata-lock deadlock inside CREATE TABLE
    # off silently ONLY when the session holds no other metadata lock. Holding a
    # named lock (the way apps serialise work) takes that away, so the loser
    # gets 1213 "Deadlock found" every time instead of by luck.
    if os.environ.get("T4_RACE_HOLD_NAMED_LOCK"):
        database.fetch_one("SELECT GET_LOCK(?, 0) AS held", [f"tina4-race-{session_id}"])
except Exception as error:  # noqa: BLE001 - the message is the finding
    sys.stderr.write(f"connect: {type(error).__name__}: {error}")
    sys.exit(2)

remaining = start_at - time.time()
if remaining > 0.01:
    time.sleep(remaining - 0.01)
while time.time() < start_at:
    pass

try:
    # write() runs _ensure_table() on its way in - this IS the first use.
    handler.write(session_id, {"worker": session_id}, 60)
except Exception as error:  # noqa: BLE001 - the message is the finding
    sys.stderr.write(f"{type(error).__name__}: {error}")
    sys.exit(1)

sys.exit(0)
