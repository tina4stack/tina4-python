"""FirebirdAdapter must release its connection on GC without warning (regression).

A caller (or a cross-engine contract test) that drops a Database backed by
Firebird WITHOUT calling close() used to let firebird-driver's OWN Connection
finalizer run a rollback on a stale/aborted transaction handle at
garbage-collection time -- ``invalid transaction handle (expecting explicit
transaction start)`` -- which the interpreter reports through
``sys.unraisablehook`` and pytest turns into a PytestUnraisableExceptionWarning.
FirebirdAdapter.__del__ now resolves the transaction and detaches first, so the
driver's finalizer finds an already-closed connection and stays silent
(FB-DEL-CLOSE).

The trigger is an operation that ABORTS the transaction (a duplicate-key insert),
then dropping the only reference without close() -- exactly the shape the
write-path contract cases hit. Needs a real Firebird (no doubles): gated on
TINA4_TEST_FIREBIRD_URL.
"""
import gc
import os
import sys

import pytest

_FB_URL = os.environ.get("TINA4_TEST_FIREBIRD_URL")


@pytest.mark.skipif(
    not _FB_URL,
    reason="TINA4_TEST_FIREBIRD_URL not set (needs a live Firebird)",
)
def test_dropping_a_firebird_adapter_does_not_warn_on_gc():
    from tina4_python.database import Database

    captured: list = []
    previous_hook = sys.unraisablehook
    sys.unraisablehook = captured.append
    try:
        db = Database(_FB_URL, "SYSDBA", "masterkey")
        try:
            db.execute("DROP TABLE fb_gc_probe")
        except Exception:  # noqa: BLE001 - first run has nothing to drop
            pass
        db.execute("CREATE TABLE fb_gc_probe (id INTEGER NOT NULL, PRIMARY KEY (id))")
        db.execute("INSERT INTO fb_gc_probe (id) VALUES (1)")
        # Abort the transaction: a duplicate primary key leaves the connection's
        # transaction in the error state whose handle the driver finalizer trips on.
        try:
            db.execute("INSERT INTO fb_gc_probe (id) VALUES (1)")
        except Exception:  # noqa: BLE001 - expected constraint violation
            pass
        # Drop the ONLY reference without close() and force finalization now.
        del db
        gc.collect()
        gc.collect()
    finally:
        sys.unraisablehook = previous_hook

    assert not captured, (
        "dropping a FirebirdAdapter raised on GC -- adapter.__del__ must resolve "
        "and detach the connection: "
        f"{[str(getattr(u, 'exc_value', u)) for u in captured]}"
    )

    # Tidy the probe table with a fresh, explicitly-closed connection.
    cleanup = Database(_FB_URL, "SYSDBA", "masterkey")
    try:
        cleanup.execute("DROP TABLE fb_gc_probe")
    except Exception:  # noqa: BLE001
        pass
    cleanup.close()
