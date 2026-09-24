# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Browser-open gate (ADR-0070) - the Python runner for browser_open_contract.json.

tests/fixtures/browser_open_contract.json is a copy of
tina4-documentation/plan/v3/fixtures/browser_open_contract.json. Every
decision_table row is fed to the real gate, run() uses, with the process
environment really set and a real .env file really loaded. No doubles: the
environment is written and restored by hand.

The mode_table describes how the native `tina4 serve` resolves its mode; a
framework's own server resolves "development" from TINA4_DEBUG, so here a row's
mode maps straight to the debug argument.
"""
import json
import os
from pathlib import Path

import pytest

from tina4_python.core.server import _CI_ENVIRONMENT_VARIABLES, _CI_NOT_SET_VALUES, _should_open_browser
from tina4_python.dotenv import is_truthy, load_env

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "browser_open_contract.json").read_text())
ROWS = FIXTURE["decision_table"]
TOUCHED = ("TINA4_NO_BROWSER", *_CI_ENVIRONMENT_VARIABLES)


def _decide(row, tmp_path) -> bool:
    saved = {name: os.environ.get(name) for name in TOUCHED}
    try:
        for name in TOUCHED:
            os.environ.pop(name, None)
        os.environ.update(row["env"])
        if row.get("dotenv"):
            env_file = tmp_path / ".env"
            env_file.write_text("".join(f"{k}={v}\n" for k, v in row["dotenv"].items()))
            load_env(str(env_file))  # never overrides the process environment
        return _should_open_browser(
            is_debug=row["mode"] == "development",
            no_browser="--no-browser" in row["flags"],
        )
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@pytest.mark.parametrize("row", ROWS, ids=[row["name"] for row in ROWS])
def test_every_decision_table_row_matches_the_python_gate(row, tmp_path):
    assert _decide(row, tmp_path) is row["opens"], row.get("why", row["name"])


def test_the_gate_reads_exactly_the_adr_0070_ci_variables():
    assert list(_CI_ENVIRONMENT_VARIABLES) == FIXTURE["ci_env_vars"]


def test_the_gate_treats_exactly_the_adr_0070_values_as_not_ci():
    assert list(_CI_NOT_SET_VALUES) == FIXTURE["ci_not_set_values"]


def test_the_truthy_set_is_the_adr_0070_truthy_set():
    for value in FIXTURE["truthy"]:
        assert is_truthy(value) and is_truthy(value.upper()) and is_truthy(f" {value} "), value
    for value in (*FIXTURE["ci_not_set_values"], "", "y", "t", "enabled", "maybe"):
        assert not is_truthy(value), value
