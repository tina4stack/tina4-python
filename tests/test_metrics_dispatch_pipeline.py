"""The dispatch pipeline's COMPLEXITY gate (feature 6, group B) - Python.

Split out of test_dispatch_pipeline.py, which keeps the assertions that need
nothing but the source: the stage lists, that every listed stage exists, is
private and takes only (ctx), and that no stage calls another.

These need the tina4 Rust CLI on PATH. Metrics is measured by the NATIVE engine
(ADR-0002) with no in-framework fallback, so CI cannot run them - the workflow
excludes this file by name alongside the other tests/test_metrics_*.py, matching
how tina4-ruby excludes `**/metrics*_spec.rb`, tina4-php tags @group metrics and
tina4-nodejs lists METRICS_FILES. The engine is tested where it lives,
tina4stack/tina4 src/metrics.rs, exercised by `cargo test` in its own pipeline.

Runs locally for anyone with the CLI installed, which is where a refactor that
regrows a god-function gets caught.

Twin of tina4-php/tests/MetricsDispatchPipelineTest.php.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tina4_python.core import server

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET = "tina4_python/core/server.py"

ALL_STAGE_NAMES = [
    s.__name__
    for s in (
        server._PRE_MATCH_STAGES
        + server._POST_MATCH_STAGES
        + server._FALLBACK_STAGES
        + server._RESPONSE_STAGES
    )
]


def _metrics_for(relative_path: str) -> dict:
    """Shell out to the SAME `tina4 metrics` the CI gate uses, so the ceiling
    asserted here cannot drift from the one that gates a release.

    Fails LOUDLY on non-JSON rather than skipping. A skipped gate is an
    unguarded ceiling that reports green - two frameworks already shipped that
    way because a package manager shadowed the `tina4` name.
    """
    cli = shutil.which("tina4")
    if cli is None:
        pytest.fail(
            "the tina4 CLI is not on PATH - the complexity gate cannot be "
            "asserted. Install it, or run this file only where it exists."
        )

    proc = subprocess.run(
        [cli, "metrics", "--json", "--path", relative_path],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    out = proc.stdout.lstrip()
    if not out.startswith("{"):
        pytest.fail(
            "tina4 metrics did not return JSON - the complexity gate cannot be "
            f"asserted. Got: {out[:120]!r} / stderr: {proc.stderr[:120]!r}"
        )
    return json.loads(out)


def _complexity_offenders(report: dict) -> list[str]:
    return [o["detail"] for o in report["offenders"] if o["kind"] == "complexity"]


def test_no_dispatch_stage_exceeds_complexity_ten():
    over = [
        detail
        for detail in _complexity_offenders(_metrics_for(TARGET))
        if any(detail.startswith(f"{stage} ") for stage in ALL_STAGE_NAMES)
    ]
    assert over == [], f"dispatch stages over the complexity ceiling: {over}"


def test_the_god_function_does_not_come_back():
    """handle() was 190 lines at cyclomatic complexity 27, and
    _finalize_response was 20. The extraction is only real while they stay
    small - _finalize_response is now six named response stages."""
    regrown = [
        detail
        for detail in _complexity_offenders(_metrics_for(TARGET))
        if detail.startswith(("handle ", "_finalize_response "))
    ]
    assert regrown == [], f"a dispatch god-function regrew: {regrown}"
