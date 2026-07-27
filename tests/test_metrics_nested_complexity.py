"""Nested functions are measured once, not charged to every enclosing function.

A function's complexity used to be measured over its whole span, so a branch
inside a nested function landed on that function AND every function around it.
The over-count compounded with depth: a wrapper around twenty inner handlers
absorbed the entire file's complexity and topped the offenders list, hiding the
real hot spots. Locked in here and mirrored in PHP, Ruby, Node and the Rust
engine.
"""

from pathlib import Path

from tina4_python.dev_admin.metrics import full_analysis


def _cc_by_name(tmp_path: Path, source: str) -> dict:
    (tmp_path / "sample.py").write_text(source)
    result = full_analysis(str(tmp_path))
    return {f["name"]: f["complexity"] for f in result["all_functions"]}


class TestNestedComplexityIsNotDoubleCounted:
    def test_a_parent_with_no_branches_of_its_own_scores_one(self, tmp_path):
        cc = _cc_by_name(tmp_path, (
            "def outer(a):\n"
            "    def inner1(x):\n"
            "        if x: return 1\n"
            "        if x > 2: return 2\n"
            "        return 3\n"
            "    def inner2(y):\n"
            "        if y: return 1\n"
            "        if y > 2: return 2\n"
            "        return 3\n"
            "    return inner1(a) + inner2(a)\n"
        ))
        # Before the fix outer reported 5: its own base plus all four inner
        # branches. The inners are unchanged - the branches moved, not vanished.
        assert cc["outer"] == 1, f"outer branches on nothing itself, got {cc['outer']}"
        assert cc["inner1"] == 3
        assert cc["inner2"] == 3

    def test_the_parent_keeps_its_own_branches(self, tmp_path):
        cc = _cc_by_name(tmp_path, (
            "def outer(a):\n"
            "    if a:\n"
            "        return 0\n"
            "    def inner(x):\n"
            "        if x: return 1\n"
            "        return 2\n"
            "    return inner(a)\n"
        ))
        assert cc["outer"] == 2, "1 + outer's own if, and nothing from inner"
        assert cc["inner"] == 2

    def test_three_levels_deep_each_keeps_only_its_own(self, tmp_path):
        cc = _cc_by_name(tmp_path, (
            "def a(x):\n"
            "    if x: pass\n"
            "    def b(y):\n"
            "        if y: pass\n"
            "        def c(z):\n"
            "            if z: pass\n"
            "            return 1\n"
            "        return c(y)\n"
            "    return b(x)\n"
        ))
        # Depth was where the old behaviour hurt most: a scored 1+3 branches.
        assert cc["a"] == 2
        assert cc["b"] == 2
        assert cc["c"] == 2

    def test_a_lambda_still_counts_toward_its_enclosing_function(self, tmp_path):
        # Lambdas are never listed as functions of their own, so excluding them
        # would silently LOSE their decisions rather than relocate them.
        cc = _cc_by_name(tmp_path, (
            "def f(xs):\n"
            "    return sorted(xs, key=lambda x: 1 if x else 0)\n"
        ))
        assert list(cc) == ["f"], f"the lambda must not be listed: {list(cc)}"
        assert cc["f"] == 2, "1 + the lambda's ternary"

    def test_a_method_in_a_nested_class_is_not_charged_to_the_function(self, tmp_path):
        cc = _cc_by_name(tmp_path, (
            "def make():\n"
            "    class Inner:\n"
            "        def go(self, x):\n"
            "            if x: return 1\n"
            "            return 2\n"
            "    return Inner\n"
        ))
        assert cc["make"] == 1
        # The method carries its class prefix.
        go = next(name for name in cc if name.endswith("go"))
        assert cc[go] == 2

    def test_sibling_methods_never_affected_each_other(self, tmp_path):
        # Guards against an over-eager fix that subtracts from siblings too.
        cc = _cc_by_name(tmp_path, (
            "class A:\n"
            "    def one(self, x):\n"
            "        if x: return 1\n"
            "        return 2\n"
            "    def two(self, y):\n"
            "        if y: return 1\n"
            "        return 2\n"
        ))
        assert cc["A.one"] == 2
        assert cc["A.two"] == 2

    def test_the_file_total_drops_to_the_sum_of_own_complexities(self, tmp_path):
        (tmp_path / "sample.py").write_text(
            "def outer(a):\n"
            "    def inner(x):\n"
            "        if x: return 1\n"
            "        return 2\n"
            "    return inner(a)\n"
        )
        result = full_analysis(str(tmp_path))
        metrics = result["file_metrics"][0]
        # 1 (outer) + 2 (inner), with nothing counted twice.
        assert metrics["complexity"] == 3
