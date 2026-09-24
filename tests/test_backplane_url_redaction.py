"""A WebSocket backplane never writes its connection password to the log.

THE BUG, MEASURED on v3 (13464d4): ``RedisBackplane.__init__`` logged
``"RedisBackplane connected to %s"`` with the raw ``TINA4_WS_BACKPLANE_URL``, so
``redis://:s3cret@host:6381/3`` went to the log verbatim, password included.
``NATSBackplane`` did the same. The fix passes the URL through
``tina4_python.database.database_url.redact_url`` - the framework's single
redaction primitive - which keeps the host and replaces the password with ``***``.

HOW IT IS MEASURED, WITHOUT A DOUBLE. A REAL child Python process builds a REAL
RedisBackplane against the lab's REAL password-protected Redis
(TINA4_TEST_REDIS_AUTH_URL), with stdlib logging configured to write to the
child's REAL stderr at INFO. The parent reads that stderr: it is exactly what an
operator's log would hold. The child also does a publish -> subscribe round trip
through the same backplane, so the test proves the URL still WORKS - a "fix"
that redacted the URL before connecting would fail AUTH and go red here.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
REDIS_AUTH_URL = os.environ.get("TINA4_TEST_REDIS_AUTH_URL", "")
REPORT_MARKER = "TINA4_REPORT "

_CHILD_SOURCE = r'''
import json
import logging
import sys
import threading
import uuid

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(name)s %(levelname)s %(message)s")

from tina4_python.websocket.backplane import RedisBackplane

url = sys.argv[1]
backplane = RedisBackplane(url=url)
received = []
arrived = threading.Event()


def on_message(message):
    received.append(message)
    arrived.set()


channel = "tina4-redaction-" + uuid.uuid4().hex
payload = "round-trip-" + uuid.uuid4().hex
backplane.subscribe(channel, on_message)
# A Redis subscription is live only once the server has acknowledged it; publish
# until the listener has it (bounded), so the round trip is not a race.
for _ in range(100):
    backplane.publish(channel, payload)
    if arrived.wait(0.05):
        break
backplane.close()
print("TINA4_REPORT " + json.dumps({"payload": payload, "received": received}))
'''


def _redis_auth_url() -> str:
    if not REDIS_AUTH_URL:
        pytest.skip("password redis not set: export TINA4_TEST_REDIS_AUTH_URL (e.g. redis://:s3cret@localhost:6381/3)")
    pytest.importorskip("redis", reason="redis client not installed (uv sync --extra test)")
    return REDIS_AUTH_URL


def _run_backplane_child(url: str) -> tuple[dict, str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("PYTHON")}
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-c", _CHILD_SOURCE, url],
        env=environment, capture_output=True, text=True, timeout=60,
    )
    for line in completed.stdout.splitlines():
        if line.startswith(REPORT_MARKER):
            return json.loads(line[len(REPORT_MARKER):]), completed.stderr
    raise AssertionError(
        f"backplane child reported nothing (exit {completed.returncode})\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )


def test_redis_backplane_log_never_contains_the_password():
    url = _redis_auth_url()
    password = urlparse(url).password
    assert password, f"TINA4_TEST_REDIS_AUTH_URL must carry a password to prove anything: {url!r}"

    report, log_output = _run_backplane_child(url)

    connected_lines = [line for line in log_output.splitlines() if "RedisBackplane connected to" in line]
    assert connected_lines, f"the backplane never logged its connect line:\n{log_output}"
    assert password not in log_output, f"the password reached the log:\n{log_output}"
    parsed = urlparse(url)
    assert f"***@{parsed.hostname}:{parsed.port}" in connected_lines[0], connected_lines[0]


def test_redis_backplane_really_works_with_the_password_url():
    url = _redis_auth_url()

    report, log_output = _run_backplane_child(url)

    assert report["received"][:1] == [report["payload"]], (
        f"publish -> subscribe did not round-trip through the password Redis:\n{report}\n{log_output}"
    )


def test_redis_backplane_refuses_the_wrong_password():
    """Negative control: the round trip above is meaningful only if this Redis
    really checks the password. A wrong one must fail to connect."""
    url = _redis_auth_url()
    parsed = urlparse(url)
    wrong = url.replace(f":{parsed.password}@", ":not-the-password@", 1)

    completed = subprocess.run(
        [sys.executable, "-c", _CHILD_SOURCE, wrong],
        env={**{k: v for k, v in os.environ.items() if not k.startswith("PYTHON")},
             "PYTHONPATH": str(REPOSITORY_ROOT), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=60,
    )
    assert completed.returncode != 0, completed.stdout
    assert REPORT_MARKER not in completed.stdout
    assert "AuthenticationError" in completed.stderr or "WRONGPASS" in completed.stderr, completed.stderr
    # The failure path logs too; the wrong password must not reach it either.
    assert "not-the-password" not in completed.stderr, completed.stderr
