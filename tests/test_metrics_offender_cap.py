"""Regression: the metrics offenders list must NOT be capped to the top-15
most-complex functions.

Latent bug (fixed): full_analysis() returned `most_complex_functions[:15]` and
offenders() sourced the complexity offenders from that capped list, so the 16th+
function over the complexity threshold was silently dropped from the offenders
list, the total_offenders count, AND the `--fail-on` gate — a genuinely
too-complex function escaped the build gate. offenders() now reads the full
`all_functions` list; `most_complex_functions[:15]` stays for the display report.

No mocks: writes a real .py file and runs the real analyzer over it.
"""

from tina4_python.dev_admin import metrics as m


def _high_cc_function(name: str, decisions: int = 22) -> str:
    # `decisions` independent `if` statements -> cyclomatic complexity = 1 + decisions.
    # 22 -> CC 23 (> 20 => "error" severity).
    body = "\n".join(f"    if {j} == {j}:\n        pass" for j in range(decisions))
    return f"def {name}():\n{body}\n"


def test_offenders_not_capped_at_top_15_complex_functions(tmp_path):
    n = 18  # > 15, so the old [:15] cap would silently drop fn15..fn17
    (tmp_path / "bigmod.py").write_text(
        "\n".join(_high_cc_function(f"fn{i}") for i in range(n))
    )

    result = m.offenders(str(tmp_path), top=100)
    complexity = [o for o in result["offenders"] if o["kind"] == "complexity"]

    # All 18 over-threshold functions must surface (old code: exactly 15).
    assert len(complexity) == n, (
        f"expected {n} complexity offenders, got {len(complexity)} "
        f"— top-15 cap regression"
    )
    # They are error-severity (CC 23 > 20) and therefore MUST reach --fail-on error.
    assert all(o["severity"] == "error" for o in complexity)
    assert result["summary"]["total_offenders"] >= n


def test_display_report_still_caps_most_complex_at_15(tmp_path):
    # The display-only report keeps its top-15 contract; only offenders() is uncapped.
    (tmp_path / "bigmod.py").write_text(
        "\n".join(_high_cc_function(f"fn{i}") for i in range(18))
    )
    analysis = m.full_analysis(str(tmp_path))
    assert len(analysis["most_complex_functions"]) == 15   # display cap intact
    assert len(analysis["all_functions"]) == 18            # full list exposed for offenders
