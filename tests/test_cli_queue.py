"""Real tests for the top-level `queue` CLI command (Phase 3, Python master).

No mocks — every test drives the ACTUAL `_queue` handlers against a REAL
file-backed tina4_python.queue.Queue in a temp directory: push real jobs, run
`work` / `stats` / `retry` / `clear`, and assert the real on-disk counts and
side effects. `work` is exercised as a bounded single-pass drain (`--once`)
running a REAL consumer module (real per-job handler, real processing), so no
mock and no leaked worker thread.
"""
import json

import pytest

from tina4_python.cli import _queue, _resolve_queue_handler
from tina4_python.queue import Queue


@pytest.fixture
def qenv(tmp_path, monkeypatch):
    """A clean, isolated file-backed queue rooted under a temp dir."""
    monkeypatch.chdir(tmp_path)  # clean cwd → _load_env() finds no project .env
    monkeypatch.setenv("TINA4_QUEUE_BACKEND", "file")
    monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path / "queue"))
    return tmp_path


class TestQueueStats:
    def test_reports_real_pending_count(self, qenv, capsys):
        q = Queue(topic="emails")
        q.push({"n": 1}); q.push({"n": 2}); q.push({"n": 3})
        _queue(["stats", "emails"])
        assert "pending    3" in capsys.readouterr().out

    def test_json_is_machine_readable_and_exact(self, qenv, capsys):
        Queue(topic="emails").push({"n": 1})
        _queue(["stats", "emails", "--json"])
        assert json.loads(capsys.readouterr().out) == {
            "topic": "emails", "pending": 1, "reserved": 0,
            "failed": 0, "dead": 0, "completed": 0,
        }

    def test_counts_dead_letter_jobs(self, qenv, capsys):
        # A job that exhausts its single retry is dead-lettered for real.
        q = Queue(topic="emails", max_retries=1)
        q.push({"n": 1})
        q.pop().fail("boom")  # attempts 1 >= max_retries 1 → dead-letter
        _queue(["stats", "emails", "--json"])
        assert json.loads(capsys.readouterr().out)["dead"] == 1

    def test_default_topic_when_omitted(self, qenv, capsys):
        Queue(topic="default").push({"n": 1})
        _queue(["stats"])
        out = capsys.readouterr().out
        assert "Queue 'default'" in out and "pending    1" in out


class TestQueueRetry:
    def test_revives_dead_letter_job_back_to_pending(self, qenv, capsys):
        q = Queue(topic="jobs", max_retries=1)
        q.push({"n": 1})
        q.pop().fail("boom")  # → dead-letter
        assert q.size("dead") == 1

        _queue(["retry", "jobs"])
        assert "Re-queued 1 job(s)" in capsys.readouterr().out

        # Real files moved out of the dead-letter store back to pending.
        assert Queue(topic="jobs").size("pending") == 1
        assert Queue(topic="jobs").size("dead") == 0

    def test_nothing_to_retry_is_zero(self, qenv, capsys):
        _queue(["retry", "jobs"])
        assert "Re-queued 0 job(s)" in capsys.readouterr().out


class TestQueueClear:
    def test_clear_pending_purges_real_jobs(self, qenv, capsys):
        q = Queue(topic="tasks")
        q.push({"n": 1}); q.push({"n": 2})
        assert q.size("pending") == 2

        _queue(["clear", "pending", "tasks"])
        assert "Cleared 2 'pending' job(s)" in capsys.readouterr().out
        assert Queue(topic="tasks").size("pending") == 0

    def test_clear_defaults_to_completed_and_default_topic(self, qenv, capsys):
        Queue(topic="tasks").push({"n": 1})
        _queue(["clear"])  # status=completed, topic=default
        assert "Cleared 0 'completed' job(s)" in capsys.readouterr().out
        # A completed-clear on the default topic leaves the tasks topic intact.
        assert Queue(topic="tasks").size("pending") == 1

    def test_clear_dead_letter(self, qenv, capsys):
        q = Queue(topic="tasks", max_retries=1)
        q.push({"n": 1})
        q.pop().fail("boom")  # → dead-letter
        assert q.size("dead") == 1
        _queue(["clear", "dead", "tasks"])
        assert "Cleared 1 'dead' job(s)" in capsys.readouterr().out
        assert Queue(topic="tasks").size("dead") == 0


def _write_consumer(services_dir, topic, results_file):
    """Write a REAL consumer module exposing topic + per-job handle."""
    services_dir.mkdir(parents=True, exist_ok=True)
    (services_dir / f"{topic}_consumer.py").write_text(
        "from pathlib import Path\n"
        f"RESULTS = Path(r'{results_file}')\n"
        "\n"
        "def handle(data):\n"
        "    if data.get('boom'):\n"
        "        raise RuntimeError('boom')\n"
        "    with RESULTS.open('a') as fh:\n"
        "        fh.write(str(data['n']) + '\\n')\n"
        "\n"
        "def consume(context=None):\n"
        "    pass\n"
        "\n"
        f"service = {{'name': '{topic}-consumer', 'topic': '{topic}', "
        "'handler': consume, 'handle': handle, 'daemon': True}\n",
        encoding="utf-8",
    )


class TestQueueWork:
    def test_once_drains_and_processes_real_jobs(self, qenv, capsys):
        services = qenv / "svc"
        results = qenv / "results.txt"
        _write_consumer(services, "greetings", results)

        q = Queue(topic="greetings")
        q.push({"n": 1}); q.push({"n": 2}); q.push({"n": 3})

        _queue(["work", "greetings", "--once", "--services", str(services)])
        out = capsys.readouterr().out

        assert "Processed 3 job(s), 0 failed" in out
        # The REAL handler ran for every job (real side effect on disk).
        assert sorted(results.read_text().split()) == ["1", "2", "3"]
        assert Queue(topic="greetings").size("pending") == 0

    def test_once_nacks_failing_job_to_dead_letter(self, qenv, capsys):
        services = qenv / "svc"
        results = qenv / "results.txt"
        _write_consumer(services, "greetings", results)

        q = Queue(topic="greetings")
        q.push({"n": 1})       # good
        q.push({"boom": True})  # poison

        _queue(["work", "greetings", "--once", "--services", str(services)])
        out = capsys.readouterr().out

        # Good job processed; poison job burned its retries → dead-letter.
        assert results.read_text().split() == ["1"]
        assert Queue(topic="greetings").size("dead") == 1
        assert "Processed 1 job(s)" in out

    def test_once_without_handler_warns_and_drains(self, qenv, capsys):
        Queue(topic="orphans").push({"n": 1})
        _queue(["work", "orphans", "--once", "--services", str(qenv / "nope")])
        out = capsys.readouterr().out
        assert "No consumer handler found" in out
        assert "Processed 1 job(s)" in out
        assert Queue(topic="orphans").size("pending") == 0


class TestResolveQueueHandler:
    def test_none_when_dir_missing(self, qenv):
        assert _resolve_queue_handler(str(qenv / "missing"), "x") is None

    def test_finds_handler_by_topic(self, qenv):
        services = qenv / "svc"
        _write_consumer(services, "greetings", qenv / "r.txt")
        handler = _resolve_queue_handler(str(services), "greetings")
        assert callable(handler)
        # Wrong topic → no match.
        assert _resolve_queue_handler(str(services), "other") is None


class TestQueueDispatchGuards:
    def test_no_subcommand_exits_nonzero(self, qenv, capsys):
        with pytest.raises(SystemExit) as exc:
            _queue([])
        assert exc.value.code == 1
        assert "work" in capsys.readouterr().out

    def test_unknown_subcommand_exits_nonzero(self, qenv, capsys):
        with pytest.raises(SystemExit) as exc:
            _queue(["frobnicate"])
        assert exc.value.code == 1
        assert "Unknown queue subcommand" in capsys.readouterr().out
