"""Lock-in tests for `tina4 metrics` — the offenders() analyzer and the CLI handler.

Engine/CLI-agnostic: builds throwaway projects on disk, runs the real
analyzer + the real CLI handler, and asserts on the structured offenders
list, the --json shape, --top truncation, the "clean" path, and every
--fail-on exit-code branch. These guard against silent drift in the
scoring rules or exit-code contract.
"""
import json
import os

import pytest

from tina4_python.cli import _metrics
from tina4_python.dev_admin import metrics as _m


# ── Fixtures ───────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clear_metrics_cache():
    """full_analysis() caches for 60s keyed on file mtimes; tmp dirs are
    fresh per test so the hash differs, but reset explicitly to be safe."""
    _m._full_cache = {"hash": "", "data": None, "time": 0}
    _m._last_scan_root = ""
    yield
    _m._full_cache = {"hash": "", "data": None, "time": 0}
    _m._last_scan_root = ""


@pytest.fixture
def in_dir(tmp_path):
    """cd into a temp dir and back out afterwards."""
    old = os.getcwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(old)


def _bad_function_source(name="messy", branches=25):
    """A function whose cyclomatic complexity exceeds 20 (an 'error' offender).

    CC = 1 + one decision point per `if`. 25 ifs → CC 26.
    """
    lines = [f"def {name}(x):"]
    for i in range(branches):
        lines.append(f"    if x == {i}:")
        lines.append(f"        return {i}")
    lines.append("    return -1")
    return "\n".join(lines) + "\n"


def _huge_file_source(loc=600):
    """A file with > 500 lines of code (a 'large_file' warn offender)."""
    return "".join(f"a{i} = {i}\n" for i in range(loc))


def _write_bad_project(root):
    """Lay down a src/ tree with a deliberately bad, untested module."""
    src = root / "src"
    src.mkdir(parents=True, exist_ok=True)
    # One module that is BOTH over-complex AND huge AND untested.
    bad = _bad_function_source() + "\n" + _huge_file_source()
    (src / "bad.py").write_text(bad, encoding="utf-8")
    return src


def _write_clean_project(root):
    """A tiny, simple, tested src/ tree → zero offenders."""
    src = root / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "clean.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    tests = root / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    # A precise referencing test so has_tests is True (not an 'untested' offender).
    (tests / "test_clean.py").write_text(
        "from src.clean import add\n\n"
        "def test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )
    return src


class TestTestDetection:
    """Regression for the dashboard 'T' badge / 'untested' offender bug: a
    module imported by a test via its FULL package path (the `src.`/package
    qualifier tests actually use) was mislabelled untested because detection
    matched only the scan-root-relative dotted path."""

    def test_full_package_path_import_counts_as_tested(self, in_dir):
        src = in_dir / "src"
        src.mkdir(parents=True, exist_ok=True)
        # No dedicated test_widget.py and no distinctive class — detection MUST
        # come from the import-path match alone.
        (src / "widget.py").write_text(
            "def compute(x):\n    return x + 1\n", encoding="utf-8"
        )
        tests = in_dir / "tests"
        tests.mkdir(parents=True, exist_ok=True)
        # Test file NOT named for the module; imports via the full `src.` path.
        (tests / "test_suite.py").write_text(
            "from src.widget import compute\n\n"
            "def test_compute():\n    assert compute(1) == 2\n",
            encoding="utf-8",
        )
        result = _m.full_analysis("src")
        widget = next(f for f in result["file_metrics"] if f["path"].endswith("widget.py"))
        assert widget["has_tests"] is True, (
            "a module imported by a test via its full package path must count as tested"
        )

    def test_short_class_name_reference_counts_as_tested(self, in_dir):
        """A 3-char PascalCase class (e.g. ORM, Api) referenced by a test is a
        real signal — the >3-char gate wrongly excluded it. The test imports the
        class via the package root, so the module path 'orm' never appears and
        detection depends SOLELY on the ORM class-symbol signal."""
        src = in_dir / "src"
        src.mkdir(parents=True, exist_ok=True)
        (src / "orm.py").write_text(
            "class ORM:\n    def save(self):\n        return True\n", encoding="utf-8"
        )
        (src / "__init__.py").write_text("from src.orm import ORM\n", encoding="utf-8")
        tests = in_dir / "tests"
        tests.mkdir(parents=True, exist_ok=True)
        (tests / "test_models.py").write_text(
            "from src import ORM\n\ndef test_save():\n    assert ORM().save()\n",
            encoding="utf-8",
        )
        result = _m.full_analysis("src")
        orm = next(f for f in result["file_metrics"] if f["path"].endswith("orm.py"))
        assert orm["has_tests"] is True, "a 3-char class referenced by a test is a real signal"


# ── offenders() — positive ─────────────────────────────────────────────

class TestOffendersPositive:
    def test_bad_project_surfaces_each_kind(self, in_dir):
        _write_bad_project(in_dir)
        result = _m.offenders("src", top=50)
        offenders = result["offenders"]
        kinds = {o["kind"] for o in offenders}

        assert "complexity" in kinds, "over-20 CC function must be flagged"
        assert "large_file" in kinds, ">500 LOC file must be flagged"
        assert "untested" in kinds, "module with no referencing test must be flagged"

        # The complexity offender is an error (CC > 20).
        complexity = next(o for o in offenders if o["kind"] == "complexity")
        assert complexity["severity"] == "error"
        assert complexity["score"] > 20
        assert "complexity" in complexity["detail"].lower()

        # large_file is a warn with score = loc/100.
        large = next(o for o in offenders if o["kind"] == "large_file")
        assert large["severity"] == "warn"
        assert "LOC" in large["detail"]

        # untested is info.
        untested = next(o for o in offenders if o["kind"] == "untested")
        assert untested["severity"] == "info"

    def test_each_offender_has_required_keys(self, in_dir):
        _write_bad_project(in_dir)
        for o in _m.offenders("src", top=50)["offenders"]:
            assert set(o) >= {"file", "line", "kind", "severity", "score", "detail"}

    def test_ranked_error_before_warn_before_info(self, in_dir):
        _write_bad_project(in_dir)
        offenders = _m.offenders("src", top=50)["offenders"]
        rank = [_m._SEVERITY_RANK[o["severity"]] for o in offenders]
        assert rank == sorted(rank, reverse=True), "must be severity-descending"
        # First item is the error-severity complexity offender.
        assert offenders[0]["severity"] == "error"

    def test_summary_carries_headline_numbers(self, in_dir):
        _write_bad_project(in_dir)
        summary = _m.offenders("src", top=5)["summary"]
        assert summary["files_analyzed"] >= 1
        assert summary["total_offenders"] >= 3
        assert "avg_complexity" in summary
        assert "avg_maintainability" in summary
        assert summary["scan_mode"] in ("project", "framework")

    def test_top_truncates(self, in_dir):
        _write_bad_project(in_dir)
        assert len(_m.offenders("src", top=1)["offenders"]) == 1


# ── offenders() — negative ──────────────────────────────────────────────

class TestOffendersNegative:
    def test_clean_project_has_no_offenders(self, in_dir):
        _write_clean_project(in_dir)
        result = _m.offenders("src", top=20)
        assert result["offenders"] == []
        assert result["summary"]["total_offenders"] == 0


# ── CLI handler — JSON output ───────────────────────────────────────────

class TestMetricsCliJson:
    def test_json_is_valid_with_summary_and_offenders(self, in_dir, capsys):
        _write_bad_project(in_dir)
        # default --fail-on absent → exit 0
        with pytest.raises(SystemExit) as exc:
            _metrics(["--json"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        parsed = json.loads(out)  # must be the ONLY thing printed
        assert "summary" in parsed and "offenders" in parsed
        assert parsed["summary"]["total_offenders"] >= 3
        assert len(parsed["offenders"]) >= 3

    def test_json_top_one(self, in_dir, capsys):
        _write_bad_project(in_dir)
        with pytest.raises(SystemExit):
            _metrics(["--json", "--top", "1"])
        parsed = json.loads(capsys.readouterr().out)
        assert len(parsed["offenders"]) == 1


# ── CLI handler — human output ──────────────────────────────────────────

class TestMetricsCliHuman:
    def test_clean_prints_friendly_line_and_exits_zero(self, in_dir, capsys):
        _write_clean_project(in_dir)
        with pytest.raises(SystemExit) as exc:
            _metrics([])
        assert exc.value.code == 0
        assert "no offenders" in capsys.readouterr().out

    def test_human_report_lists_offenders(self, in_dir, capsys):
        _write_bad_project(in_dir)
        with pytest.raises(SystemExit) as exc:
            _metrics([])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "Tina4 Metrics" in out
        assert "SEVERITY" in out
        assert "complexity" in out


# ── CLI handler — exit codes (--fail-on) ────────────────────────────────

class TestMetricsCliFailOn:
    def test_default_no_fail_on_exits_zero_even_with_offenders(self, in_dir, capsys):
        _write_bad_project(in_dir)
        with pytest.raises(SystemExit) as exc:
            _metrics(["--json"])
        capsys.readouterr()
        assert exc.value.code == 0

    def test_fail_on_error_nonzero_when_error_present(self, in_dir, capsys):
        _write_bad_project(in_dir)  # has an error-severity complexity offender
        with pytest.raises(SystemExit) as exc:
            _metrics(["--json", "--fail-on", "error"])
        capsys.readouterr()
        assert exc.value.code == 1

    def test_fail_on_warn_nonzero_when_offenders_present(self, in_dir, capsys):
        _write_bad_project(in_dir)
        with pytest.raises(SystemExit) as exc:
            _metrics(["--json", "--fail-on", "warn"])
        capsys.readouterr()
        assert exc.value.code == 1

    def test_fail_on_error_zero_when_only_warn_info(self, in_dir, capsys):
        # 25 trivial functions, untested: offenders are warn
        # (too_many_functions) + info (untested), and — critically — small
        # enough that maintainability stays healthy, so NO error offender.
        src = in_dir / "src"
        src.mkdir(parents=True, exist_ok=True)
        body = "".join(f"def f{i}():\n    return {i}\n\n" for i in range(25))
        (src / "many.py").write_text(body, encoding="utf-8")

        with pytest.raises(SystemExit) as exc:
            _metrics(["--json", "--fail-on", "error"])
        parsed = json.loads(capsys.readouterr().out)
        severities = {o["severity"] for o in parsed["offenders"]}
        assert "error" not in severities, "fixture must produce no error offenders"
        assert {"warn", "info"} & severities, "fixture must produce warn/info offenders"
        assert exc.value.code == 0, "--fail-on error must ignore warn/info"

    def test_fail_on_warn_nonzero_when_warn_only(self, in_dir, capsys):
        src = in_dir / "src"
        src.mkdir(parents=True, exist_ok=True)
        body = "".join(f"def f{i}():\n    return {i}\n\n" for i in range(25))
        (src / "many.py").write_text(body, encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            _metrics(["--json", "--fail-on", "warn"])
        capsys.readouterr()
        assert exc.value.code == 1

    def test_clean_project_fail_on_warn_exits_zero(self, in_dir, capsys):
        _write_clean_project(in_dir)
        with pytest.raises(SystemExit) as exc:
            _metrics(["--json", "--fail-on", "warn"])
        capsys.readouterr()
        assert exc.value.code == 0
