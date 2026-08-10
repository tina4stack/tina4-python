"""Fail-closed runner for the audited Tina4 3.14 DotEnv contract.

The audit owns the cases in ``fixtures/dotenv_corpus.json``. Every case must
have exactly one behavioural executor before the framework can claim Feature 1
conformance. Missing executors are failures, never skips or xfails.
"""

from collections.abc import Callable
import json
from pathlib import Path

import pytest


FIXTURE = Path(__file__).parent / "fixtures" / "dotenv_corpus.json"
CONTRACT = json.loads(FIXTURE.read_text(encoding="utf-8"))["contract_3_14"]
CASES = CONTRACT["cases"]

# Implementation work registers one real-filesystem/process-environment
# executor per case. Keeping this empty now is deliberate: the completed audit
# must make the suite red until Feature 1 actually implements its contract.
EXECUTORS: dict[str, Callable[[dict], None]] = {}


def _case_id(case: dict) -> str:
    return case["id"]


def test_contract_case_ids_and_witnesses_are_unique() -> None:
    ids = [_case_id(case) for case in CASES]
    witnesses = [case["witness"] for case in CASES]
    assert len(ids) == 46
    assert len(ids) == len(set(ids))
    assert len(witnesses) == len(set(witnesses))


def test_executor_registry_has_no_unknown_cases() -> None:
    fixture_ids = {_case_id(case) for case in CASES}
    assert set(EXECUTORS) <= fixture_ids


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_dotenv_contract_314(case: dict) -> None:
    case_id = _case_id(case)
    executor = EXECUTORS.get(case_id)
    assert executor is not None, (
        f"{case_id}: contract_3_14 executor not implemented; "
        f"witness={case['witness']}"
    )
    executor(case)
