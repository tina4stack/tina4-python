"""The metrics engine contract (ADR-0002): one engine, no fallback.

The hand-rolled AST analyzer that used to live in dev_admin/metrics.py is gone.
Everything except the instant file census now comes from `tina4 metrics --json`,
so a number measured in Python is comparable with the same number measured in
PHP, Ruby or Node.

These run the REAL binary over REAL source. No doubles: the whole point of the
change is that exactly one implementation exists, and a fake would test a second.

The previous version of this file tested `adapt_payload`, a pure shaping function
on a shim since folded into metrics.py. That seam is gone, so the shaping is
proved end to end instead - a stronger claim than the unit test was.
"""

import shutil
import textwrap

import pytest

from tina4_python.dev_admin.metrics import (
    MetricsEngineError,
    file_detail,
    full_analysis,
)

pytestmark = pytest.mark.skipif(
    shutil.which("tina4") is None,
    reason="the metrics engine IS the tina4 CLI; without it there is nothing to test",
)


@pytest.fixture
def project(tmp_path):
    """A small real project: one module with a class, one test referencing it."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "orders.py").write_text(
        textwrap.dedent(
            """
            class Order:
                def total(self, lines):
                    total = 0
                    for line in lines:
                        if line.get("qty"):
                            total += line["qty"] * line["price"]
                    return total
            """
        ).lstrip(),
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_orders.py").write_text(
        "from src.orders import Order\n\ndef test_total():\n    assert Order().total([]) == 0\n",
        encoding="utf-8",
    )
    return tmp_path


# ── the engine is present and names itself ───────────────────────────


def test_full_analysis_is_stamped_as_coming_from_the_cli(project):
    result = full_analysis(str(project / "src"))
    assert result["engine"] == "tina4-cli", (
        "the payload must name its engine, so a dashboard can never silently "
        "display numbers from somewhere else"
    )


# ── the shape the dashboard renders ──────────────────────────────────


def test_full_analysis_carries_every_field_the_dashboard_reads(project):
    result = full_analysis(str(project / "src"))
    for key in (
        "files_analyzed",
        "total_functions",
        "avg_complexity",
        "avg_maintainability",
        "file_metrics",
        "most_complex_functions",
        "dependency_graph",
        "scan_mode",
        "scan_root",
    ):
        assert key in result, f"missing dashboard field {key}"

    assert result["files_analyzed"] >= 1
    first = result["file_metrics"][0]
    for key in ("path", "loc", "avg_complexity", "maintainability", "has_referencing_test"):
        assert key in first, f"missing per-file field {key}"


def test_scan_mode_and_root_are_decided_by_the_framework(project):
    """The engine always reports "project" because it cannot know which directory
    holds a framework package. That label is the framework's to set."""
    result = full_analysis(str(project / "src"))
    assert result["scan_mode"] in ("project", "framework")
    assert str(project) in result["scan_root"]


def test_most_complex_functions_is_display_capped_at_15(project):
    result = full_analysis(str(project / "src"))
    assert len(result["most_complex_functions"]) <= 15


# ── per-file detail ──────────────────────────────────────────────────


def test_file_detail_describes_one_file(project):
    detail = file_detail(str(project / "src" / "orders.py"))
    assert detail["path"].endswith("orders.py")
    assert detail["loc"] >= 1
    assert detail["engine"] == "tina4-cli"
    assert detail["function_count"] >= 1
    assert isinstance(detail["functions"], list)
    assert any(function["name"].endswith("total") for function in detail["functions"])


def test_a_class_referenced_by_a_test_reports_a_test_reference(project):
    """The class-symbol signal. tests/test_orders.py imports Order, and that is
    what makes orders.py tested. Fixed in the CLI (stage 3 of module_has_tests);
    asserted from here so the framework cannot regress against an older engine
    without a test saying so."""
    result = full_analysis(str(project / "src"))
    orders = next(f for f in result["file_metrics"] if f["path"].endswith("orders.py"))
    assert orders["has_referencing_test"] is True
    assert "has_tests" not in orders


# ── no fallback: failure is loud ─────────────────────────────────────


def test_a_missing_path_raises_instead_of_returning_empty():
    with pytest.raises(MetricsEngineError) as exc:
        file_detail("does/not/exist.py")
    assert "no such file" in str(exc.value)


def test_a_directory_passed_to_file_detail_raises(tmp_path):
    with pytest.raises(MetricsEngineError) as exc:
        file_detail(str(tmp_path))
    assert "not a file" in str(exc.value)


def test_file_detail_needs_a_path():
    with pytest.raises(MetricsEngineError):
        file_detail("")


def test_the_error_names_the_fix():
    """A developer who hits this must be told what to install, not merely that
    something failed. The message carries the install command."""
    from tina4_python.dev_admin.metrics import _INSTALL_HINT

    assert "install.sh" in _INSTALL_HINT or "tina4.com" in _INSTALL_HINT
