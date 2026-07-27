"""The tina4 CLI metrics engine adapter (ADR-0002).

These run the REAL tina4 binary over REAL files. No doubles: the adapter's whole
job is to decide whether an actual CLI on this machine can serve the dashboard,
and a fake CLI would prove nothing about that.
"""

import json
import os
import subprocess
from pathlib import Path

from tina4_python.dev_admin.metrics import full_analysis, resolve_scan_target
from tina4_python.dev_admin.metrics_engine import adapt_payload, engine_analysis, engine_path

DASHBOARD_KEYS = (
    "files_analyzed",
    "total_functions",
    "avg_complexity",
    "avg_maintainability",
    "file_metrics",
    "most_complex_functions",
    "dependency_graph",
    "scan_mode",
    "scan_root",
)


class TestEngineAnalysis:
    def test_returns_either_none_or_a_complete_dashboard_payload(self, tmp_path):
        """Whatever the installed CLI is, the contract holds or we get None.

        Asserting a specific version would make this test a lie on any other
        machine. What must always be true: the adapter never hands the dashboard
        a payload with a field missing.
        """
        (tmp_path / "leaf.py").write_text("def leaf():\n    return 1\n")
        (tmp_path / "top.py").write_text("import leaf\n\ndef top():\n    return leaf.leaf()\n")

        result = engine_analysis(str(tmp_path), "project")
        if result is None:
            # None is only allowed for a REASON: no binary, or a CLI whose engine
            # predates the rich blocks. Prove which, rather than waving it through.
            binary = engine_path()
            if binary is None:
                return
            proc = subprocess.run(
                [binary, "metrics", "--path", str(tmp_path), "--json"],
                capture_output=True, text=True, timeout=60,
            )
            payload = json.loads(proc.stdout) if proc.stdout.strip() else {}
            missing = [k for k in ("file_metrics", "most_complex_functions") if k not in payload]
            assert missing or proc.returncode != 0, (
                "the CLI emitted a full payload but the adapter rejected it"
            )
            return
        for key in DASHBOARD_KEYS:
            assert key in result, f"engine payload is missing {key}"
        assert result["engine"] == "tina4-cli"
        assert result["scan_mode"] == "project"
        for fn in result["most_complex_functions"]:
            assert "loc" in fn and "name" in fn

    def test_returns_none_when_no_tina4_is_on_path(self, tmp_path):
        """A real environment with no binary - not a stubbed lookup."""
        original = os.environ.get("PATH", "")
        os.environ["PATH"] = str(tmp_path)
        try:
            assert engine_path() is None
            assert engine_analysis(str(tmp_path), "project") is None
        finally:
            os.environ["PATH"] = original

    def test_returns_none_for_a_directory_that_does_not_exist(self):
        assert engine_analysis("/nonexistent/tina4/metrics/target", "project") is None


class TestAdaptPayload:
    def _complete(self):
        return {
            "summary": {
                "files_analyzed": 2,
                "total_functions": 3,
                "avg_complexity": 1.5,
                "avg_maintainability": 80.0,
                "scan_mode": "project",
                "scan_root": "src",
                "total_offenders": 0,
            },
            "file_metrics": [{
                "path": "a.py", "loc": 10, "avg_complexity": 1.0,
                "maintainability": 80.0, "has_tests": False,
                "coupling_afferent": 1, "coupling_efferent": 0, "instability": 0.0,
            }],
            "most_complex_functions": [{
                "name": "f", "file": "a.py", "line": 1, "complexity": 2, "loc": 4,
            }],
            "dependency_graph": {"b.py": ["a.py"]},
        }

    def test_flattens_summary_to_the_top_level(self):
        out = adapt_payload(self._complete(), "src", "project")
        assert out["files_analyzed"] == 2
        assert out["avg_maintainability"] == 80.0
        assert out["dependency_graph"] == {"b.py": ["a.py"]}

    def test_the_framework_owns_scan_mode_not_the_engine(self):
        """The engine always says "project" - it cannot know a framework package."""
        payload = self._complete()
        assert payload["summary"]["scan_mode"] == "project"
        out = adapt_payload(payload, "src", "framework")
        assert out["scan_mode"] == "framework"

    def test_rejects_a_payload_whose_functions_have_no_loc(self):
        """The dashboard's function table has a LOC column, so a payload without
        per-function loc would render "undefined" in every row. This is why the
        adapter checks the DATA rather than a version string."""
        payload = self._complete()
        del payload["most_complex_functions"][0]["loc"]
        assert adapt_payload(payload, "src") is None

    def test_rejects_a_payload_with_empty_function_objects(self):
        """Defensive: a serialisation regression that emits bare objects must be
        caught here, not rendered as a table of "undefined"."""
        payload = self._complete()
        payload["most_complex_functions"] = [{}]
        assert adapt_payload(payload, "src") is None

    def test_rejects_a_payload_missing_a_summary_scalar(self):
        payload = self._complete()
        del payload["summary"]["avg_complexity"]
        assert adapt_payload(payload, "src") is None

    def test_rejects_a_payload_with_no_summary_at_all(self):
        assert adapt_payload({"file_metrics": [], "most_complex_functions": []}, "src") is None

    def test_rejects_a_file_metric_missing_a_rendered_field(self):
        payload = self._complete()
        del payload["file_metrics"][0]["has_tests"]
        assert adapt_payload(payload, "src") is None

    def test_accepts_an_empty_but_well_formed_scan(self):
        """An empty directory is a valid answer, not a broken payload."""
        payload = self._complete()
        payload["file_metrics"] = []
        payload["most_complex_functions"] = []
        out = adapt_payload(payload, "src")
        assert out is not None and out["file_metrics"] == []

    def test_caps_the_function_table_at_fifteen(self):
        payload = self._complete()
        one = payload["most_complex_functions"][0]
        payload["most_complex_functions"] = [dict(one) for _ in range(40)]
        assert len(adapt_payload(payload, "src")["most_complex_functions"]) == 15

    def test_rejects_a_non_dict(self):
        assert adapt_payload([], "src") is None


class TestSharedScanTarget:
    def test_resolve_scan_target_matches_what_full_analysis_reports(self):
        """Both producers must agree about what was measured, or the dashboard
        label contradicts the numbers underneath it."""
        root, scan_mode = resolve_scan_target()
        assert scan_mode == full_analysis()["scan_mode"]
        assert Path(root).exists()

    def test_an_explicit_package_directory_is_reported_as_framework(self):
        import tina4_python
        pkg = str(Path(tina4_python.__file__).parent)
        _, scan_mode = resolve_scan_target(pkg)
        assert scan_mode == "framework"


class TestRealCliContract:
    def test_the_cli_emits_json_we_can_parse_at_all(self, tmp_path):
        """Guards the wire contract itself: if `tina4 metrics --json` stops being
        JSON, the adapter must find out here rather than in a browser."""
        binary = engine_path()
        if binary is None:
            return
        (tmp_path / "x.py").write_text("def x():\n    return 1\n")
        proc = subprocess.run(
            [binary, "metrics", "--path", str(tmp_path), "--json"],
            capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert isinstance(payload, dict)
        # "summary" is the one block every released CLI emits - the richer
        # file_metrics / most_complex_functions / dependency_graph blocks arrived
        # with the engine rewrite, which is exactly what the adapter probes for.
        assert "summary" in payload, f"unexpected --json shape: {sorted(payload)}"
        assert "files_analyzed" in payload["summary"]
        rich = ("file_metrics", "most_complex_functions", "dependency_graph")
        if all(k in payload for k in rich):
            assert adapt_payload(payload, str(tmp_path)) is not None, (
                "a CLI that emits every rich block must satisfy the adapter"
            )
