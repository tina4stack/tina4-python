"""Real-subprocess tests for the scaffolding envelope v1.1 (ADR-0063 Wave 1).

3.13.120 bumps the generate resolution envelope from `generate_v1` to
`generate_v1_1` with two additive keys on `resolution`:

- `edit_hints[]` — one entry per `tina4:edit` marker found in the
  freshly-written source, shape `{file, line, label}`. The generator
  templates bake these markers at first-edit spots (add fields, guard
  the request, add validation rules, …) so a caller can point a
  follow-up patch straight at them.
- `next[]` — a short curated list of actionable next-steps per verb
  (edit this, migrate that, try this curl). Empty for a target that has
  no obvious next-step.

The envelope also surfaces `test_paths[]` (already in v1 but never
printed) in the human stderr block under "tests", and prints the new
sections under "Edit these lines:" and "Next:". Every v1 key is
preserved — a v1 consumer keeps working unchanged.

NO mocks. Each case shells out to a fresh Python subprocess running the
real `tina4_python.cli.main` entrypoint, in a pytest tmp_path project
scaffold, so what these tests observe is exactly what the CLI does
end-to-end.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys

# Same launcher shape as tests/test_generate_resolution.py so a v1 and v1.1
# consumer look identical to the CLI — one entrypoint, one process, one env.
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


# The marker syntax the generator templates bake in — matched anywhere on a
# stripped line. Case 4 uses this to prove the envelope's file:line address
# actually points at a real marker, not fabricated from the template's shape.
# Kept as a plain regex so a change to the marker syntax fails the test loud
# instead of drifting the shape silently.
_MARKER = re.compile(r"(?:#|--|\{#)\s*tina4:edit\s+")


# ── 1. Positive: dry-run model returns v1.1 envelope with populated keys ──

def test_generate_model_json_dry_run_carries_edit_hints_and_next(tmp_path):
    """`generate model Foo --json --dry-run` emits the v1.1 envelope with
    populated `edit_hints[]` (from the baked template markers) and `next[]`
    (curated next-steps). Every v1 key is preserved — the shape is purely
    additive, so a v1 consumer sees exactly what it saw before.
    """
    result = _run(tmp_path, ["tina4python", "generate", "model", "Foo",
                             "--json", "--dry-run"])
    assert result.returncode == 0, (
        f"exit {result.returncode}; stderr={result.stderr!r}"
    )

    envelope = json.loads(result.stdout)
    resolution = envelope["resolution"]

    # v1 keys preserved intact — an existing consumer still parses fine.
    assert envelope["command"] == "generate"
    assert envelope["target"] == "model"
    assert envelope["dry_run"] is True
    assert envelope["actions_taken"] == []
    assert resolution["class_name"] == "Foo"
    assert resolution["table_name"] == "foo"
    assert resolution["file_path"] == "src/orm/Foo.py"
    assert resolution["test_paths"] == ["tests/test_foo_model.py"]

    # v1.1 additive keys — both present, both populated for a model call.
    hints = resolution["edit_hints"]
    assert isinstance(hints, list) and hints, (
        f"edit_hints empty for a template that bakes markers: {resolution!r}"
    )
    for hint in hints:
        assert set(hint) == {"file", "line", "label"}, hint
        assert isinstance(hint["file"], str) and hint["file"]
        assert isinstance(hint["line"], int) and hint["line"] > 0
        assert isinstance(hint["label"], str) and hint["label"]
        # Labels are short actionable phrases — no punctuation-noise, no
        # exclamations, no questions. If the marker syntax drifts, this
        # goes loud rather than shipping a formatting regression.
        assert not hint["label"].endswith(("?", ".")), hint

    # Both baked hints are present in a fresh model file.
    labels = {h["label"] for h in hints}
    assert "add fields here" in labels, labels
    assert any("add relationships here" in lbl for lbl in labels), labels

    steps = resolution["next"]
    assert isinstance(steps, list) and steps, (
        f"next[] empty for a target with curated steps: {resolution!r}"
    )
    # Curated content stays actionable — must name the file to edit AND the
    # command to run. Every entry is a real user-facing string.
    joined = "\n".join(steps)
    assert "src/orm/Foo.py" in joined
    assert "tina4 migrate" in joined
    assert "tina4 serve" in joined

    # Dry-run still writes nothing to the caller's cwd — the in-memory tmpdir
    # scan for markers must not leak files into the project.
    on_disk = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")
                     if p.is_file())
    assert on_disk == [], f"dry-run wrote files: {on_disk!r}"


# ── 1b. A LOGIC-shaped generator is wired too: queue carries the fill points ──

def test_generate_queue_json_dry_run_carries_edit_hints_and_next(tmp_path):
    """`generate queue <topic> --json --dry-run` emits the v1.1 envelope with a
    populated `edit_hints[]` (the queue-consumer template bakes a `tina4:edit`
    marker at the job handler) and curated `next[]` steps.

    Before this, `queue` was NOT in `_RESOLUTION_TARGETS`, so `generate queue`
    printed a bare `Created X` with no envelope and no fill points - a logic-
    shaped generator that scaffolded a consumer and then went silent about what
    to edit next. This is the regression that keeps the AI-fill contract on it.
    """
    result = _run(tmp_path, ["tina4python", "generate", "queue", "order-emails",
                             "--json", "--dry-run"])
    assert result.returncode == 0, (
        f"exit {result.returncode}; stderr={result.stderr!r}"
    )

    envelope = json.loads(result.stdout)
    resolution = envelope["resolution"]

    assert envelope["target"] == "queue"
    assert envelope["dry_run"] is True
    assert envelope["actions_taken"] == []
    assert resolution["file_path"] == "src/services/order_emails_consumer.py"
    assert resolution["test_paths"] == ["tests/test_order_emails.py"]

    # THE fix: the baked marker surfaces as an edit hint (the AI fill point).
    hints = resolution["edit_hints"]
    assert isinstance(hints, list) and hints, (
        f"queue envelope has no edit_hints - the fill point was not surfaced: {resolution!r}"
    )
    for hint in hints:
        assert set(hint) == {"file", "line", "label"}, hint
        assert hint["file"] == "src/services/order_emails_consumer.py"
        assert isinstance(hint["line"], int) and hint["line"] > 0
        assert isinstance(hint["label"], str) and hint["label"]
    assert any("job payload" in h["label"] for h in hints), [h["label"] for h in hints]

    # Curated next[] names the file to edit AND the produce/run path.
    steps = resolution["next"]
    assert isinstance(steps, list) and steps
    joined = "\n".join(steps)
    assert "src/services/order_emails_consumer.py" in joined
    assert "publish_order_emails" in joined

    on_disk = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")
                     if p.is_file())
    assert on_disk == [], f"dry-run wrote files: {on_disk!r}"


# ── 2. Manifest: contract advertises v1.1 / generate_v1_1 ─────────────────

def test_commands_manifest_advertises_v1_1_contract(tmp_path):
    """`commands --json` advertises the bumped `resolution_contract` so an
    agent can programmatically gate on the new envelope shape.
    """
    result = _run(tmp_path, ["tina4python", "commands", "--json"])
    assert result.returncode == 0, (
        f"exit {result.returncode}; stderr={result.stderr!r}"
    )

    manifest = json.loads(result.stdout[result.stdout.find("{"):])
    contract = manifest["resolution_contract"]
    assert contract["version"] == "1.1", contract
    assert contract["envelope"] == "generate_v1_1", contract


# ── 3. Human block: bare generate prints "Edit these lines:" + "Next:" ────

def test_bare_generate_prints_edit_and_next_sections_on_stderr(tmp_path):
    """A bare `generate model Foo` writes real files AND prints the two new
    sections to STDERR under "Edit these lines:" and "Next:", plus the
    existing "tests" row (was in the envelope since v1, now surfaced too).
    Stdout is untouched by the block — a caller parsing stdout stays clean.
    """
    result = _run(tmp_path, ["tina4python", "generate", "model", "Foo"])
    assert result.returncode == 0, (
        f"exit {result.returncode}; stderr={result.stderr!r}"
    )

    stderr = result.stderr

    # Section headers land on stderr.
    assert "Edit these lines:" in stderr, stderr
    assert "Next:" in stderr, stderr
    assert "tests      tests/test_foo_model.py" in stderr, stderr

    # Each section carries real content, not just a header.
    edit_body = stderr.split("Edit these lines:", 1)[1].split("Next:", 1)[0]
    assert "src/orm/Foo.py:" in edit_body, edit_body
    assert "add fields here" in edit_body, edit_body

    next_body = stderr.split("Next:", 1)[1]
    assert "1." in next_body, next_body
    assert "tina4 migrate" in next_body, next_body

    # Real files landed on disk — this is NOT a dry-run.
    assert (tmp_path / "src" / "orm" / "Foo.py").is_file()
    assert (tmp_path / "tests" / "test_foo_model.py").is_file()
    assert list((tmp_path / "migrations").glob("*_create_foo.sql")), \
        "expected a *_create_foo.sql migration on the real write path"


# ── 4. Marker match: each edit_hint address points at a real marker line ──

def test_edit_hint_file_line_points_at_a_real_marker(tmp_path):
    """Every edit-hint's `file:line` MUST address a line that actually
    starts with the `tina4:edit` marker syntax in the written file — the
    envelope must never fabricate positions. Also mutation-proven: stripping
    the marker from a copy of the file drops that hint from a re-scan.
    """
    # First: real write + envelope on the same call, so the envelope's
    # addresses are what the writer produced byte-for-byte.
    result = _run(tmp_path, ["tina4python", "generate", "model", "Foo",
                             "--json"])
    assert result.returncode == 0, (
        f"exit {result.returncode}; stderr={result.stderr!r}"
    )
    envelope = json.loads(result.stdout)
    hints = envelope["resolution"]["edit_hints"]
    assert hints, f"expected non-empty hints for a bare model generate: {envelope!r}"

    # Every hint must resolve to a real line that carries the marker syntax.
    for hint in hints:
        file_path = tmp_path / hint["file"]
        assert file_path.is_file(), f"envelope named a missing file: {hint}"
        lines = file_path.read_text(encoding="utf-8").splitlines()
        assert 1 <= hint["line"] <= len(lines), (
            f"line {hint['line']} out of range for {hint['file']} "
            f"(len={len(lines)})"
        )
        line = lines[hint["line"] - 1]
        assert _MARKER.search(line), (
            f"hint {hint!r} points at line {line!r} "
            f"which has no tina4:edit marker"
        )
        assert hint["label"] in line, (
            f"hint label {hint['label']!r} not in line {line!r}"
        )

    # Mutation gate: strip the FIRST hint's marker from the file, re-scan on
    # a fresh subprocess, and prove the hint disappears. A green test that
    # never sees red is not a gate — this proves the scan actually reads
    # the file rather than reproducing template constants.
    first = hints[0]
    doomed = tmp_path / first["file"]
    original = doomed.read_text(encoding="utf-8")
    lines = original.splitlines()
    lines[first["line"] - 1] = "    # removed by the mutation test"
    doomed.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # `--dry-run` re-emits the envelope by re-rendering the template in a
    # tmpdir — that path is NOT the disk scan, and would still see the
    # marker. Use the unit path instead: call the real helper against the
    # mutated file so what we prove is the DISK-based grep, which is what
    # the write path (case 1 above) actually runs.
    proof = subprocess.run(
        [sys.executable, "-c",
         "from pathlib import Path\n"
         "from tina4_python.cli import _scan_edit_hints\n"
         "import json, sys\n"
         "hints = _scan_edit_hints(Path(sys.argv[1]), [sys.argv[2]])\n"
         "print(json.dumps(hints))\n",
         str(tmp_path), first["file"]],
        capture_output=True, text=True, timeout=30,
    )
    assert proof.returncode == 0, (
        f"scan helper failed: {proof.returncode}\n"
        f"stdout={proof.stdout!r}\nstderr={proof.stderr!r}"
    )
    rescan = json.loads(proof.stdout)
    labels_after = {h["label"] for h in rescan}
    assert first["label"] not in labels_after, (
        f"mutation gate: stripped marker {first['label']!r} still surfaced "
        f"after the rewrite. rescan={rescan!r}"
    )


# ── 5. Empty-arrays legal: keys always present, [] never omitted ──────────

def test_empty_arrays_are_shipped_as_empty_lists_not_omitted(tmp_path):
    """A target with no markers to hint at (a route without --model, whose
    handlers are AI-FILL stubs — no baked `tina4:edit` lines) still returns
    valid JSON with `edit_hints: []`. The contract is that the keys ALWAYS
    exist so a v1.1 consumer can `envelope["resolution"]["edit_hints"]`
    unconditionally without a fallback.
    """
    result = _run(tmp_path, ["tina4python", "generate", "route", "notes",
                             "--json", "--dry-run"])
    assert result.returncode == 0, (
        f"exit {result.returncode}; stderr={result.stderr!r}"
    )
    envelope = json.loads(result.stdout)
    resolution = envelope["resolution"]

    # The keys always exist — the shape never omits them.
    assert "edit_hints" in resolution, resolution
    assert "next" in resolution, resolution

    # A no-model route bakes no tina4:edit markers (AI-FILL is the marker
    # of its own kind). `edit_hints` is therefore an empty list, NOT null
    # and NOT missing.
    assert resolution["edit_hints"] == [], resolution["edit_hints"]

    # The `next[]` list is still curated for the route target, so it is
    # non-empty here. What matters for this case is the empty-shape half.
    assert isinstance(resolution["next"], list)
