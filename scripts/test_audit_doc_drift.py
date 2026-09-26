# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Mutation-proof for the doc-drift gate.

Every assertion here breaks the thing the gate guards and proves the gate goes
RED, then proves the real repo is GREEN -- so the gate is a gate, not a ghost.
"""
import tempfile
import unittest
from pathlib import Path

import audit_doc_drift as gate

REPO_ROOT = gate.REPO_ROOT


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


class DocDriftGateTest(unittest.TestCase):
    def test_repo_is_clean(self):
        # The live tree (after the fixes) must pass. Sibling tina4-js beside us.
        problems = gate.check(REPO_ROOT, REPO_ROOT.parent / "tina4-js")
        # Filter the js check when the sibling repo is absent (single-repo dev):
        js_missing = any("tina4-js source not found" in p for p in problems)
        real = [p for p in problems if "tina4-js source not found" not in p]
        self.assertEqual(real, [], f"unexpected doc drift: {real}")
        if js_missing:
            self.skipTest("tina4-js sibling not checked out; js-import check not exercised here")

    def test_claude_md_flags_nonexistent_class(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write(root, "tina4_python/CLAUDE.md",
                   "```python\nfrom tina4_python.crud import AutoCrud\n"
                   "return response(CRUD.to_crud(request, {}))\n```\n")
            problems = gate.check_claude_md(root)
            self.assertTrue(any("CRUD.to_crud" in p for p in problems), problems)

    def test_claude_md_accepts_real_api(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write(root, "tina4_python/CLAUDE.md",
                   "```python\nfrom tina4_python.crud import AutoCrud\n"
                   "AutoCrud.register(User)\nAutoCrud.discover('src/orm')\n```\n")
            self.assertEqual(gate.check_claude_md(root), [])

    def test_claude_md_flags_missing_method_on_real_class(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write(root, "tina4_python/CLAUDE.md",
                   "```python\nfrom tina4_python.crud import AutoCrud\n"
                   "AutoCrud.summon_everything()\n```\n")
            problems = gate.check_claude_md(root)
            self.assertTrue(any("summon_everything" in p for p in problems), problems)

    def test_where_return_type_flags_plain_list(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "data-and-orm.md"
            path.write_text("The `where()` method returns a plain list of models.\n")
            problems = gate._check_where_return_type(path)
            self.assertTrue(any("plain list" in p for p in problems), problems)

    def test_where_return_type_accepts_model_collection(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "data-and-orm.md"
            path.write_text("The `where()` method returns a `ModelCollection`.\n")
            self.assertEqual(gate._check_where_return_type(path), [])

    def test_websocket_signature_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "auth-and-services.md"
            path.write_text("```python\n@websocket('/ws')\nasync def chat(connection):\n    pass\n```\n")
            problems = gate._check_ws_and_order(path)
            self.assertTrue(any("@websocket handler signature" in p for p in problems), problems)

    def test_websocket_signature_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "auth-and-services.md"
            path.write_text("```python\n@websocket('/ws')\nasync def chat(connection, event, data):\n    pass\n```\n")
            self.assertEqual(gate._check_ws_and_order(path), [])

    def test_decorator_order_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "auth-and-services.md"
            path.write_text("```python\n@post('/login')\n@noauth()\nasync def login(request, response):\n    pass\n```\n")
            problems = gate._check_ws_and_order(path)
            self.assertTrue(any("@noauth() appears below @post" in p for p in problems), problems)

    def test_decorator_order_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "auth-and-services.md"
            path.write_text("```python\n@noauth()\n@post('/login')\nasync def login(request, response):\n    pass\n```\n")
            self.assertEqual(gate._check_ws_and_order(path), [])

    def test_js_import_flags_missing_export(self):
        js = REPO_ROOT.parent / "tina4-js"
        if not (js / "src" / "index.ts").exists():
            self.skipTest("tina4-js sibling not checked out")
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write(root, ".claude/skills/tina4-js/references/rtc.md",
                   "```ts\nimport { mount } from 'tina4js';\n```\n")
            problems = gate.check_js_skill(root, js)
            self.assertTrue(any("`mount` is not exported" in p for p in problems), problems)

    def test_js_import_accepts_real_export(self):
        js = REPO_ROOT.parent / "tina4-js"
        if not (js / "src" / "index.ts").exists():
            self.skipTest("tina4-js sibling not checked out")
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write(root, ".claude/skills/tina4-js/references/rtc.md",
                   "```ts\nimport { html, effect } from 'tina4js';\n```\n")
            self.assertEqual(gate.check_js_skill(root, js), [])


if __name__ == "__main__":
    unittest.main()
