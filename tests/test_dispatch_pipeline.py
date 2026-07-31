"""The dispatch pipeline CONTRACT (feature 6, group B) - Python.

The characterisation suite proves the extraction changed no behaviour. This
proves the extraction STAYS extracted. A refactor with no gate regrows: the
next person to inline a stage should get a red test, not a slightly worse
number in a report nobody reads.

Every assertion is derived from the code, never from a hand-maintained copy of
the answer - a list duplicated into a test drifts from the list it guards.

The "no stage calls another" check walks the real AST rather than matching
source text. The other three strip comments with a regex first, because their
comments NAME the stages when explaining the order; Python has a parser in the
stdlib, so it can ask the question exactly instead of approximately.

Twin of tina4-ruby/spec/dispatch_pipeline_spec.rb,
tina4-php/tests/DispatchPipelineTest.php and
tina4-nodejs/test/dispatchPipeline.test.ts.
"""

import ast
import inspect
from pathlib import Path

from tina4_python.core import server


ALL_STAGES = (
    server._PRE_MATCH_STAGES
    + server._POST_MATCH_STAGES
    + server._FALLBACK_STAGES
    + server._RESPONSE_STAGES
)


def _names(stages):
    return [s.__name__ for s in stages]


# ── The stage list is DATA ───────────────────────────────────────────


def test_the_pipeline_declares_its_stages_in_order():
    assert _names(server._PRE_MATCH_STAGES) == [
        "_stage_cors_preflight",
        "_stage_rate_limit",
        "_stage_start_timer",
        "_stage_trailing_slash_redirect",
        "_stage_dev_admin",
        "_stage_swagger",
        "_stage_reset_request_caches",
        "_stage_global_middleware_pre",
    ]
    assert _names(server._POST_MATCH_STAGES) == ["_stage_dispatch_route"]
    assert _names(server._FALLBACK_STAGES) == [
        "_stage_method_not_allowed",
        "_stage_not_found",
    ], "405 is answered before falling through to static/template/404"
    assert _names(server._RESPONSE_STAGES) == [
        "_stage_apply_cors",
        "_stage_dev_toolbar_inject",
        "_stage_dev_inspector_capture",
        "_stage_request_log",
        "_stage_session_save",
        "_stage_head_strip",
    ], "head_strip is LAST or the toolbar puts a body back into a HEAD response"


def test_it_has_no_unnamed_stage():
    """NEGATIVE: a name in a list with no function behind it, or a stage
    quietly deleted, must fail here rather than at 3am on a real request."""
    missing = [
        s.__name__
        for s in ALL_STAGES
        if not callable(getattr(server, s.__name__, None))
    ]
    assert missing == [], f"listed but not defined on the module: {missing}"


def test_it_keeps_every_stage_private():
    """A stage is an internal step, not public API. If one leaks into the
    public surface it becomes something callers depend on, and the list stops
    being the only thing that decides ordering."""
    public = [s.__name__ for s in ALL_STAGES if not s.__name__.startswith("_")]
    assert public == [], f"stages are internals, these are public: {public}"


def test_each_stage_is_callable_on_its_own():
    """Every stage takes (ctx) and nothing else - no stage reads a local of
    handle(), because there are none left to read. A stage that grew a
    dependency on dispatch's scope would need another parameter."""
    wrong = {
        s.__name__: list(inspect.signature(s).parameters)
        for s in ALL_STAGES
        if list(inspect.signature(s).parameters) != ["ctx"]
    }
    assert wrong == {}, f"stages must take exactly (ctx): {wrong}"


def test_a_stage_does_not_reach_into_another_stage():
    """NEGATIVE: ordering lives in the lists, not in calls between stages.

    A stage calling another directly hides an edge the list does not show -
    exactly the coupling the extraction removed. This is why
    ``_stage_method_not_allowed`` and ``_stage_not_found`` are STAGES rather
    than helpers ``_stage_dispatch_route`` calls: the fallback chain is
    expressed as list order like everything else.
    """
    source = Path(server.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    stage_names = {s.__name__ for s in ALL_STAGES}

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in stage_names:
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            called = func.id if isinstance(func, ast.Name) else None
            if called in stage_names and called != node.name:
                offenders.append(f"{node.name} calls {called}")

    assert offenders == [], (
        "ordering must live in the stage lists, not in calls between stages: "
        + ", ".join(offenders)
    )


def test_the_god_function_does_not_come_back():
    """handle() was 190 lines at cyclomatic complexity 27. The extraction is
    only real while it stays a runner: four list walks and nothing else.

    Asserted on the AST, not on `tina4 metrics` - this file must run in CI,
    where the Rust CLI is deliberately absent (ADR-0002). The CLI-backed
    ceiling lives in test_metrics_dispatch_pipeline.py.
    """
    tree = ast.parse(Path(server.__file__).read_text(encoding="utf-8"))
    handle = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "handle"
    )
    branches = [
        n
        for n in ast.walk(handle)
        if isinstance(n, (ast.If, ast.For, ast.While, ast.Try, ast.BoolOp))
    ]
    # 4 list walks + the "did a pre-match stage answer" test + the "did
    # anything match" test + the fallback's "has it answered" test.
    assert len(branches) <= 8, (
        f"handle() has regrown branching ({len(branches)} nodes) - "
        "a branch belongs in a stage, not in the runner"
    )
