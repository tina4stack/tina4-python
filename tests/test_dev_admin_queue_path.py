"""The dev-admin queue panel must LIST the same store it COUNTS.

Regression tests for a cluster of defects in ``/__dev/api/queue`` where the job
list described a different set of jobs from the stats printed above it — in
both directions, depending on which store had jobs in it.

  1. THE DIRECTORY. ``_api_queue``/``_api_queue_topics`` scanned a hardcoded
     ``os.getcwd()/data/queue`` while ``Queue.size()`` reads the LiteBackend's
     base path, which honours ``TINA4_QUEUE_PATH``. Set that variable — any
     container that moved the store off the ephemeral filesystem, any operator
     who put it on a volume — and the panel listed one directory and counted
     another.
  2. THE SET. A reserved job was counted by ``stats.reserved`` and never listed.
     A failed-but-retryable job — which lives in the PENDING directory with
     status "pending" — was listed TWICE: once by the directory scan and again
     by ``queue.failed()``, which re-reads those very same files.
  3. MAXRETRIES. Dead letters were listed via ``queue.dead_letters()``, which
     filters on the DEV ADMIN's own max_retries (3). A job dead-lettered by an
     app configured ``max_retries=1`` was counted by ``stats.failed`` and never
     appeared in the list.
  4. And in Python only: ``Queue.dead_letters()`` returns ``Job`` OBJECTS, not
     dicts, so the ``j["status"] = "dead_letter"`` in ``_api_queue`` raised
     ``TypeError: 'Job' object does not support item assignment``. The blanket
     ``except`` swallowed it and the WHOLE endpoint returned an empty job list
     with all-zero stats the moment one real dead letter existed. The sibling
     ``/__dev/api/queue/dead-letters`` serialised those same Job objects through
     ``json.dumps(default=str)``, emitting ``"<...Job object at 0x...>"``
     strings instead of job records.

Everything here runs against a REAL Tina4 server on a REAL port, with a REAL
file-backed queue whose job files are written by the REAL ``Queue`` API, over
REAL HTTP. No mocks, no stubs, no in-test stand-ins.
"""
import http.client
import json
import subprocess
from pathlib import Path

from conftest import boot_child_server

from tina4_python.queue import Queue


# ── Real HTTP + real server plumbing ────────────────────────────────────────

def _get_json(port: int, path: str) -> dict:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request("GET", path)
        r = conn.getresponse()
        body = r.read().decode("utf-8", errors="replace")
    finally:
        conn.close()
    assert r.status == 200, f"GET {path} -> {r.status}: {body[:400]}"
    return json.loads(body)


def _boot(tmp_path, queue_path: Path | None):
    """Boot a real dev-mode Tina4 server. ``queue_path`` becomes TINA4_QUEUE_PATH
    for the child; None means the DEFAULT configuration (no variable set at all),
    where the store is ``data/queue`` under the server's working directory.

    Returns (proc, port, project_dir). The caller reaps proc.
    """
    project: dict = {}

    def write_app(proj: Path, port: int) -> None:
        project["dir"] = proj
        (proj / ".env").write_text(
            "TINA4_DEBUG=true\nTINA4_LOG_LEVEL=ERROR\nTINA4_OVERRIDE_CLIENT=true\n"
        )
        (proj / "app.py").write_text("from tina4_python.core import run\nrun()\n")

    def dev_queue_api_is_up(port: int) -> bool:
        """Readiness is about the ENDPOINT, not just an open socket."""
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/__dev/api/queue")
            ok = conn.getresponse().status == 200
            conn.close()
            return ok
        except (OSError, http.client.HTTPException):
            return False

    proc, port = boot_child_server(
        tmp_path,
        write_app,
        extra_env={"TINA4_QUEUE_PATH": str(queue_path)} if queue_path else None,
        # The outer environment must never leak a queue path into the child —
        # this test process sets one for its own Queue instances.
        unset_env=("TINA4_QUEUE_PATH",),
        boot_timeout=25,
        ready=dev_queue_api_is_up,
    )
    return proc, port, project["dir"]


def _reap(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _queue_at(monkeypatch, store: Path, topic: str = "default", **kwargs) -> Queue:
    """A REAL Queue whose file store is ``store``.

    LiteBackend resolves TINA4_QUEUE_PATH at construction, so pointing the
    variable at a directory and building a Queue is exactly what an application
    configured that way does. The jobs it writes are real job files.
    """
    monkeypatch.setenv("TINA4_QUEUE_PATH", str(store))
    return Queue(topic=topic, **kwargs)


def _ids(jobs) -> list:
    return [j.get("id") for j in jobs]


def _stat_sum(stats: dict) -> int:
    return sum(stats[k] for k in ("pending", "completed", "failed", "reserved"))


# ── 1. THE DIRECTORY ────────────────────────────────────────────────────────

def test_job_list_reads_the_store_the_stats_count_when_queue_path_is_set(tmp_path, monkeypatch):
    """With TINA4_QUEUE_PATH set, the panel lists the REAL store — and a stale
    job at the legacy cwd/data/queue path is not listed at all."""
    store = tmp_path / "volume" / "queue"
    proc, port, proj = _boot(tmp_path, store)
    try:
        real = _queue_at(monkeypatch, store)
        real_ids = [real.push({"n": 1}), real.push({"n": 2})]

        # A REAL stale job at the legacy path the dev admin used to hardcode.
        stale = _queue_at(monkeypatch, proj / "data" / "queue")
        stale_id = stale.push({"n": "stale"})

        payload = _get_json(port, "/__dev/api/queue")
        listed = _ids(payload["jobs"])

        assert "error" not in payload, payload.get("error")
        assert sorted(listed) == sorted(real_ids), (
            f"listed {listed}, real store holds {real_ids}"
        )
        assert stale_id not in listed, (
            "a stale job under cwd/data/queue was listed even though "
            "TINA4_QUEUE_PATH points somewhere else"
        )
        assert payload["stats"]["pending"] == 2
        assert _stat_sum(payload["stats"]) == len(payload["jobs"])
    finally:
        _reap(proc)


def test_topics_endpoint_lists_the_real_store_not_the_legacy_path(tmp_path, monkeypatch):
    """/__dev/api/queue/topics had the identical hardcoded path."""
    store = tmp_path / "volume" / "queue"
    proc, port, proj = _boot(tmp_path, store)
    try:
        _queue_at(monkeypatch, store, topic="emails").push({"to": "a@b.c"})
        _queue_at(monkeypatch, proj / "data" / "queue", topic="ghost").push({"n": 0})

        topics = _get_json(port, "/__dev/api/queue/topics")["topics"]

        assert "emails" in topics, f"real topic missing from {topics}"
        assert "ghost" not in topics, (
            f"legacy cwd/data/queue topic leaked into {topics}"
        )
    finally:
        _reap(proc)


# ── 2. THE SET (default configuration — no TINA4_QUEUE_PATH) ────────────────

def test_a_failed_but_retryable_job_is_listed_exactly_once(tmp_path, monkeypatch):
    """A job that failed but still has retries left lives in the PENDING dir.
    The old code listed it once from the directory scan and again from
    queue.failed() — two rows, two contradictory statuses, for one job."""
    proc, port, proj = _boot(tmp_path, None)
    try:
        store = proj / "data" / "queue"
        queue = _queue_at(monkeypatch, store, max_retries=3)
        retryable_id = queue.push({"n": "retryable"})
        job = queue.pop()
        job.fail("boom")  # attempts 1 < 3 -> back to the pending dir
        queue.push({"n": "fresh"})

        payload = _get_json(port, "/__dev/api/queue")
        listed = _ids(payload["jobs"])

        assert "error" not in payload, payload.get("error")
        assert listed.count(retryable_id) == 1, (
            f"the failed-but-retryable job appears {listed.count(retryable_id)} "
            f"times in {listed}"
        )
        assert len(listed) == len(set(listed)), f"duplicate ids in {listed}"
        assert _stat_sum(payload["stats"]) == len(payload["jobs"]), (
            f"stats {payload['stats']} do not sum to {len(payload['jobs'])} jobs"
        )
    finally:
        _reap(proc)


def test_a_reserved_job_is_listed_and_matches_its_stat(tmp_path, monkeypatch):
    """A popped-but-unacknowledged job was counted by stats.reserved and never
    listed."""
    proc, port, proj = _boot(tmp_path, None)
    try:
        store = proj / "data" / "queue"
        queue = _queue_at(monkeypatch, store)
        reserved_id = queue.push({"n": "in-flight"})
        queue.pop()  # reserved, never completed or failed

        payload = _get_json(port, "/__dev/api/queue")
        reserved = [j for j in payload["jobs"] if j.get("status") == "reserved"]

        assert "error" not in payload, payload.get("error")
        assert payload["stats"]["reserved"] == 1
        assert _ids(reserved) == [reserved_id], (
            f"reserved job not listed; jobs were {payload['jobs']}"
        )
        assert len(reserved) == payload["stats"]["reserved"]
        assert _stat_sum(payload["stats"]) == len(payload["jobs"])
    finally:
        _reap(proc)


# ── 3. MAXRETRIES ───────────────────────────────────────────────────────────

def test_a_dead_letter_under_the_apps_own_max_retries_is_listed(tmp_path, monkeypatch):
    """An app configured max_retries=1 dead-letters at attempts=1. The old list
    filtered dead letters by the DEV ADMIN's max_retries (3), so this job was
    counted by stats.failed and never appeared."""
    proc, port, proj = _boot(tmp_path, None)
    try:
        store = proj / "data" / "queue"
        queue = _queue_at(monkeypatch, store, max_retries=1)
        dead_id = queue.push({"n": "one-shot"})
        queue.pop().fail("boom")  # attempts 1 >= max_retries 1 -> failed/

        payload = _get_json(port, "/__dev/api/queue")

        assert "error" not in payload, payload.get("error")
        assert payload["stats"]["failed"] == 1
        assert dead_id in _ids(payload["jobs"]), (
            f"dead letter counted by stats.failed but not listed: {payload}"
        )
        assert _stat_sum(payload["stats"]) == len(payload["jobs"])
    finally:
        _reap(proc)


# ── 4. The Python-only collapse ─────────────────────────────────────────────

def test_the_endpoint_does_not_collapse_when_a_dead_letter_exists(tmp_path, monkeypatch):
    """Queue.dead_letters() returns Job OBJECTS in Python. Assigning
    j["status"] raised TypeError, and the blanket except returned an empty list
    with all-zero stats — the whole panel went blank."""
    proc, port, proj = _boot(tmp_path, None)
    try:
        store = proj / "data" / "queue"
        queue = _queue_at(monkeypatch, store, max_retries=3)
        dead_id = queue.push({"n": "doomed"})
        for _ in range(3):
            queue.pop().fail("boom")  # attempts 3 >= 3 -> failed/

        payload = _get_json(port, "/__dev/api/queue")

        assert "error" not in payload, (
            f"endpoint reported an error instead of jobs: {payload.get('error')}"
        )
        assert payload["stats"]["failed"] == 1, payload["stats"]
        assert dead_id in _ids(payload["jobs"]), payload
        assert _stat_sum(payload["stats"]) == len(payload["jobs"])
    finally:
        _reap(proc)


def test_dead_letters_endpoint_returns_records_not_object_reprs(tmp_path, monkeypatch):
    """/__dev/api/queue/dead-letters serialised Job objects through
    json.dumps(default=str), so every entry was the string
    "<tina4_python.queue.job.Job object at 0x...>" — and it applied the dev
    admin's own max_retries, hiding a job an app dead-lettered at 1 attempt."""
    proc, port, proj = _boot(tmp_path, None)
    try:
        store = proj / "data" / "queue"
        # attempts 3 — visible to the dev admin's own max_retries of 3, so this
        # half is about the SHAPE of what comes back, not the filter.
        three = _queue_at(monkeypatch, store, topic="three", max_retries=3)
        three_id = three.push({"n": "doomed"})
        for _ in range(3):
            three.pop().fail("boom")

        payload = _get_json(port, "/__dev/api/queue/dead-letters?topic=three")
        assert all(isinstance(j, dict) for j in payload["jobs"]), (
            f"job records expected, got object reprs: {payload['jobs']}"
        )
        assert _ids(payload["jobs"]) == [three_id], payload

        # attempts 1 — invisible to the dev admin's max_retries of 3. This half
        # is about the FILTER: the endpoint must report what the store holds,
        # not what the dev admin's own retry limit would keep.
        one = _queue_at(monkeypatch, store, topic="one", max_retries=1)
        one_id = one.push({"n": "one-shot"})
        one.pop().fail("boom")

        payload = _get_json(port, "/__dev/api/queue/dead-letters?topic=one")
        assert _ids(payload["jobs"]) == [one_id], payload
        assert payload["count"] == 1
    finally:
        _reap(proc)


# ── Each ?status= filter returns exactly what its stat counts ───────────────

def test_each_status_filter_returns_exactly_what_its_stat_counts(tmp_path, monkeypatch):
    """One job in every bucket at once: pending, reserved and dead-lettered."""
    proc, port, proj = _boot(tmp_path, None)
    try:
        store = proj / "data" / "queue"
        queue = _queue_at(monkeypatch, store, max_retries=1)
        dead_id = queue.push({"n": "dead"})
        queue.pop().fail("boom")            # -> failed/
        reserved_id = queue.push({"n": "reserved"})
        queue.pop()                          # -> reserved/
        pending_id = queue.push({"n": "pending"})

        everything = _get_json(port, "/__dev/api/queue")
        stats = everything["stats"]

        assert "error" not in everything, everything.get("error")
        assert stats == {"pending": 1, "completed": 0, "failed": 1, "reserved": 1}, stats
        assert _stat_sum(stats) == len(everything["jobs"]) == 3, everything
        assert sorted(_ids(everything["jobs"])) == sorted([dead_id, reserved_id, pending_id])

        pending = _get_json(port, "/__dev/api/queue?status=pending")["jobs"]
        assert _ids(pending) == [pending_id], pending
        assert len(pending) == stats["pending"]

        reserved = _get_json(port, "/__dev/api/queue?status=reserved")["jobs"]
        assert _ids(reserved) == [reserved_id], reserved
        assert len(reserved) == stats["reserved"]

        failed = _get_json(port, "/__dev/api/queue?status=failed")["jobs"]
        assert _ids(failed) == [dead_id], failed
        assert len(failed) == stats["failed"]

        dead = _get_json(port, "/__dev/api/queue?status=dead")["jobs"]
        assert _ids(dead) == [dead_id], dead
        assert len(dead) == stats["failed"]
    finally:
        _reap(proc)
