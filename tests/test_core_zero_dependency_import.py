"""Zero-dependency-at-import guard (parity with the Node core-barrel guard).

Importing Tina4's public feature/core surface must pull in ONLY the stdlib and
tina4_python -- never a third-party package. The heavy optional backends
(cryptography for Web Push / RS256, message brokers, cloud clients) are imported
lazily inside the code path that needs them, so an app that never uses a feature
never pays for its dependency. A future feature that adds a top-level
`import somepkg` to a core module would load it for EVERY app; this catches that.

Measured mock-free in a FRESH subprocess: the test runner has already imported
pytest and cryptography, so an in-process check would be blind to what the
framework itself pulls.
"""
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The public surface an app imports -- including `tina4_python.database`, whose
# adapter layer now registers every optional driver LAZILY (only SQLite, stdlib,
# is eager), so importing it no longer drags firebird-driver + protobuf + dateutil
# into a SQLite or Postgres app. Connecting to a given engine loads only that
# engine's driver (see test_the_database_module_and_a_sqlite_connect_stay_zero_dep).
SURFACE = [
    "tina4_python",
    "tina4_python.core.server", "tina4_python.core.router", "tina4_python.core.events",
    "tina4_python.orm", "tina4_python.database", "tina4_python.auth", "tina4_python.frond",
    "tina4_python.queue", "tina4_python.api", "tina4_python.swagger", "tina4_python.push",
    "tina4_python.ai", "tina4_python.graphql", "tina4_python.wsdl", "tina4_python.session",
    "tina4_python.cache", "tina4_python.i18n", "tina4_python.container",
    "tina4_python.messenger", "tina4_python.crud",
]


def test_the_core_feature_surface_imports_no_third_party_package():
    imports = "\n".join(f"import {m}" for m in SURFACE)
    code = (
        "import sys, json\n"
        "before = set(sys.modules)\n"
        f"{imports}\n"
        "added = set(sys.modules) - before\n"
        "tp = sorted({n.split('.')[0] for n in added\n"
        "  if getattr(sys.modules.get(n), '__file__', None)\n"
        "  and ('site-packages' in (sys.modules[n].__file__ or '')\n"
        "       or 'dist-packages' in (sys.modules[n].__file__ or ''))\n"
        "  and n.split('.')[0] != 'tina4_python'})\n"
        "print(json.dumps(tp))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=str(REPO_ROOT)
    )
    assert result.returncode == 0, f"importing the feature surface failed:\n{result.stderr}"
    third_party = json.loads(result.stdout.strip().splitlines()[-1])
    assert third_party == [], (
        "importing the Tina4 feature/core surface eagerly loaded third-party "
        f"package(s) {third_party} -- import a heavy dependency lazily (inside the "
        "function that needs it), not at module top level, so apps that never use "
        "the feature never pay for it"
    )


def test_the_database_module_and_a_sqlite_connect_stay_zero_dep():
    """A real SQLite app -- import the database module AND open a live SQLite
    connection -- must load NO third-party driver. Every non-SQLite adapter is
    registered lazily (import on first connect to that scheme), so connecting to
    SQLite never drags psycopg2 / firebird-driver / protobuf / pymongo in. Real
    connection, no mock.
    """
    code = (
        "import sys, json\n"
        "before = set(sys.modules)\n"
        "from tina4_python.database import Database\n"
        "db = Database('sqlite:///:memory:')\n"
        "db.execute('CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)')\n"
        "db.execute('INSERT INTO t (name) VALUES (?)', ['alice'])\n"
        "assert db.fetch('SELECT name FROM t').records == [{'name': 'alice'}]\n"
        "added = set(sys.modules) - before\n"
        "tp = sorted({n.split('.')[0] for n in added\n"
        "  if getattr(sys.modules.get(n), '__file__', None)\n"
        "  and ('site-packages' in (sys.modules[n].__file__ or '')\n"
        "       or 'dist-packages' in (sys.modules[n].__file__ or ''))\n"
        "  and n.split('.')[0] != 'tina4_python'})\n"
        "print(json.dumps(tp))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=str(REPO_ROOT)
    )
    assert result.returncode == 0, f"the SQLite app failed:\n{result.stderr}"
    third_party = json.loads(result.stdout.strip().splitlines()[-1])
    assert third_party == [], (
        f"a SQLite app eagerly loaded third-party package(s) {third_party} -- a "
        "database adapter must import its driver only when its own scheme is "
        "connected, never at framework-import time"
    )
