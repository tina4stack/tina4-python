"""Real-subprocess parity between `migrate:create` and `generate migration`.

Both CLI paths emit the ADR-0063 `generate_v1_1` envelope, the same
`tina4:edit` markers in the freshly-written migration file, and the same
next-steps block. The only intentional difference is test co-emission:
`migrate:create` is a single-file operation by contract and never writes a
sibling test; `generate migration` defaults to `emit_test=True` and MAY
co-emit one (for CREATE migrations that have real DDL to assert against).

The runner used to shell out through `tina4_python.migration.create_migration`
directly and print a bare `Created: <path>` — no envelope, no markers, no
next-steps — so an agent hitting either surface got a different contract
depending on which one it typed. This test locks in the unified envelope.

NO mocks. Each case shells out to a fresh Python subprocess running the real
`tina4_python.cli.main` entrypoint under a per-test `tmp_path`, so what these
tests observe is exactly what the CLI does end-to-end.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys

# Same launcher shape as tests/test_generate_envelope_v1_1.py — one entrypoint,
# one process, one env. Nothing on PATH matters; the subprocess imports the
# module directly.
CLI_INVOKE = (
    "import sys; sys.argv={argv!r}; "
    "from tina4_python.cli import main; main()"
)


def _run(tmp_path, argv, extra_env=None):
    """Run the real CLI in a fresh subprocess under `tmp_path`."""
    env = None
    if extra_env is not None:
        import os
        env = {**os.environ, **extra_env}
    return subprocess.run(
        [sys.executable, "-c", CLI_INVOKE.format(argv=argv)],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def _project_files(tmp_path):
    """All files anywhere under tmp_path — used to prove --dry-run wrote none."""
    return sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")
                  if p.is_file())


# Marker the templates bake at first-edit spots. Case 2 uses this to prove the
# generated migration file actually carries markers instead of just having an
# empty `edit_hints[]` in the envelope.
_MARKER = re.compile(r"(?:#|--|\{#)\s*tina4:edit\s+")


# ── 1. Positive parity: both --json --dry-run envelopes are identical ─────

def test_migrate_create_and_generate_migration_produce_same_envelope(tmp_path):
    """`migrate:create <desc> --json --dry-run` and
    `generate migration <desc> --json --dry-run` must return envelopes that
    match on target, command, edit_hints[] labels, next[] steps, and every
    resolution key that is not the timestamped filename. Timestamps differ
    between the two subprocess invocations (they run seconds apart), so the
    filename is normalised out before comparing paths.

    "add users" is deliberately NOT a `create_` name: for a non-create
    migration, `generate migration` doesn't co-emit a test anyway, so the
    envelopes carry the same empty `test_paths[]` and there is no drift to
    hide behind. Test co-emission is asserted separately in case 3.
    """
    migrate_create = _run(
        tmp_path,
        ["tina4python", "migrate:create", "add_users", "--json", "--dry-run"],
    )
    assert migrate_create.returncode == 0, (
        f"migrate:create exit {migrate_create.returncode}; "
        f"stdout={migrate_create.stdout!r} stderr={migrate_create.stderr!r}"
    )
    generate_migration = _run(
        tmp_path,
        ["tina4python", "generate", "migration", "add_users",
         "--json", "--dry-run"],
    )
    assert generate_migration.returncode == 0, (
        f"generate migration exit {generate_migration.returncode}; "
        f"stderr={generate_migration.stderr!r}"
    )

    mc = json.loads(migrate_create.stdout)
    gm = json.loads(generate_migration.stdout)

    # Envelope top-level parity: both paths speak `generate migration`.
    assert mc["command"] == "generate" == gm["command"]
    assert mc["target"] == "migration" == gm["target"]
    assert mc["dry_run"] is True is gm["dry_run"]
    assert mc["actions_taken"] == [] == gm["actions_taken"]
    assert mc["input"] == gm["input"] == {"name": "add_users", "fields": None}

    # Resolution parity: paths and next-steps and markers all match. Filenames
    # carry a per-call timestamp so we strip it before comparing paths.
    def _norm(res):
        # Both subprocesses run seconds apart, so EVERY timestamped filename in
        # the envelope differs by its 14-digit stamp — not just the top-level
        # file_path/migration_path but also the nested edit_hints[].file. Strip
        # the stamp everywhere via a JSON round-trip so the comparison is about
        # the CONTRACT, not the wall-clock second each subprocess happened to run.
        blob = json.dumps(res, sort_keys=True)
        return json.loads(re.sub(r"\d{14}_", "TS_", blob))

    assert _norm(mc["resolution"]) == _norm(gm["resolution"])

    # Explicit spot-checks (in case _norm regresses): edit_hints labels and
    # the next[] array must match byte-for-byte.
    hint_labels = lambda envelope: [
        h["label"] for h in envelope["resolution"]["edit_hints"]
    ]
    assert hint_labels(mc) == hint_labels(gm)
    assert mc["resolution"]["next"] == gm["resolution"]["next"]

    # Both surfaces advertise the same envelope schema in the manifest so a
    # caller can pin against `resolution_contract` without caring which one
    # emitted the envelope.
    manifest = _run(tmp_path, ["tina4python", "commands", "--json"])
    assert manifest.returncode == 0, manifest.stderr
    contract = json.loads(manifest.stdout)["resolution_contract"]
    assert contract == {"version": "1.1", "envelope": "generate_v1_1"}

    # Dry-run wrote no files.
    assert _project_files(tmp_path) == [], (
        f"dry-run wrote files: {_project_files(tmp_path)!r}"
    )


# ── 2. File-shape parity: real invocations produce equivalent migrations ──

def test_real_writes_produce_equivalent_up_and_down_sql(tmp_path):
    """A real (non-dry-run) `migrate:create` and a real `generate migration`
    both write a `{timestamp}_{name}.sql` file (plus its `.down.sql` sibling)
    with UP and DOWN sections and at least one `tina4:edit` marker between
    them. Timestamps and filenames differ; the SQL body — with the header
    timestamp stripped — must be identical, which is the file-shape guarantee
    the two surfaces share.
    """
    # Each surface writes into its own subdir so their `migrations/` folders
    # don't cross-populate and confuse a directory listing.
    for surface, argv in (
        ("mc", ["tina4python", "migrate:create", "add_index_to_orders"]),
        ("gm", ["tina4python", "generate", "migration", "add_index_to_orders"]),
    ):
        sub = tmp_path / surface
        sub.mkdir()
        result = _run(sub, argv)
        assert result.returncode == 0, (
            f"{surface} exit {result.returncode}; stderr={result.stderr!r}"
        )
        migrations = sorted((sub / "migrations").iterdir())
        # Exactly the .sql + .down.sql pair for this migration.
        assert len(migrations) == 2, (
            f"{surface} wrote unexpected files: {[m.name for m in migrations]!r}"
        )
        up = next(m for m in migrations if m.name.endswith(".sql")
                  and not m.name.endswith(".down.sql"))
        down = next(m for m in migrations if m.name.endswith(".down.sql"))

        # Filename shape: 14-digit timestamp, then the snake_cased description.
        assert re.match(r"\d{14}_add_index_to_orders\.sql$", up.name), up.name
        assert re.match(r"\d{14}_add_index_to_orders\.down\.sql$", down.name), (
            down.name
        )
        # `tina4:edit` markers are in both files so an agent can point a
        # follow-up patch at where the SQL still needs to be filled in.
        assert _MARKER.search(up.read_text()), (
            f"{surface} UP file missing tina4:edit marker: {up.read_text()!r}"
        )
        assert _MARKER.search(down.read_text()), (
            f"{surface} DOWN file missing tina4:edit marker: {down.read_text()!r}"
        )

    # File bodies must be equivalent modulo the header `-- Created: ...` line
    # (each subprocess invocation runs a wall-clock second apart so those
    # timestamps naturally differ) — that is the file-shape parity.
    def _strip_timestamps(text: str) -> str:
        return re.sub(r"-- Created: [^\n]+\n", "-- Created: TS\n", text)

    def _up_of(surface: str) -> str:
        # `.down.sql` also matches `*.sql`, so filter explicitly to get the UP.
        return next(
            p for p in (tmp_path / surface / "migrations").glob("*.sql")
            if not p.name.endswith(".down.sql")
        ).read_text()

    def _down_of(surface: str) -> str:
        return next(
            (tmp_path / surface / "migrations").glob("*.down.sql")
        ).read_text()

    mc_up = _strip_timestamps(_up_of("mc"))
    gm_up = _strip_timestamps(_up_of("gm"))
    assert mc_up == gm_up, (
        f"UP bodies differ:\nmigrate:create={mc_up!r}\ngenerate migration={gm_up!r}"
    )
    mc_down = _strip_timestamps(_down_of("mc"))
    gm_down = _strip_timestamps(_down_of("gm"))
    assert mc_down == gm_down, (
        f"DOWN bodies differ:\nmigrate:create={mc_down!r}\ngenerate migration={gm_down!r}"
    )


# ── 3. Test co-emission difference: migrate:create writes no test file ────

def test_migrate_create_never_writes_a_test_file(tmp_path):
    """`migrate:create create_products` writes ONLY the .sql + .down.sql pair,
    even for a CREATE migration (whose DDL would otherwise be asserted by a
    co-emitted test). `generate migration create_products` — same input —
    DOES co-emit `tests/test_products_migration.py`. That is the one
    intentional divergence between the two surfaces: `migrate:create` is a
    single-file operation, `generate migration` scaffolds the pair (code +
    test) by default.
    """
    # migrate:create → only migration files, no test
    mc = tmp_path / "mc"
    mc.mkdir()
    result = _run(mc, ["tina4python", "migrate:create", "create_products"])
    assert result.returncode == 0, result.stderr
    mc_files = _project_files(mc)
    assert any(f.startswith("migrations/") and f.endswith(".sql") for f in mc_files), (
        f"migrate:create wrote no .sql: {mc_files!r}"
    )
    assert not any(f.startswith("tests/") for f in mc_files), (
        f"migrate:create must not co-emit a test, but wrote: {mc_files!r}"
    )
    # Its envelope agrees — `test_paths` is empty even for a `create_` name.
    mc_json = _run(
        tmp_path,
        ["tina4python", "migrate:create", "create_products",
         "--json", "--dry-run"],
    )
    assert mc_json.returncode == 0, mc_json.stderr
    assert json.loads(mc_json.stdout)["resolution"]["test_paths"] == []

    # generate migration → same .sql + .down.sql, plus a real co-emitted test.
    gm = tmp_path / "gm"
    gm.mkdir()
    result = _run(gm, ["tina4python", "generate", "migration", "create_products"])
    assert result.returncode == 0, result.stderr
    gm_files = _project_files(gm)
    assert any(f == "tests/test_products_migration.py" for f in gm_files), (
        f"generate migration did NOT co-emit its test: {gm_files!r}"
    )
    # Its envelope agrees — `test_paths` names the file it just wrote.
    gm_json = _run(
        tmp_path,
        ["tina4python", "generate", "migration", "create_products",
         "--json", "--dry-run"],
    )
    assert gm_json.returncode == 0, gm_json.stderr
    assert json.loads(gm_json.stdout)["resolution"]["test_paths"] == [
        "tests/test_products_migration.py"
    ]


# ── 4. Error paths: missing args → both exit non-zero with Usage line ─────

def test_missing_args_prints_usage_and_exits_non_zero(tmp_path):
    """Both surfaces refuse to invent a description out of thin air. A caller
    that types only the verb sees a helpful `Usage:` line on stdout and a
    non-zero exit so a CI step fails loud.
    """
    mc = _run(tmp_path, ["tina4python", "migrate:create"])
    assert mc.returncode != 0, mc.stdout
    assert "Usage:" in mc.stdout, mc.stdout
    assert "migrate:create" in mc.stdout, mc.stdout

    gm = _run(tmp_path, ["tina4python", "generate", "migration"])
    assert gm.returncode != 0, gm.stdout
    assert "Usage:" in gm.stdout, gm.stdout
