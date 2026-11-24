# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""McpServer.write_claude_config() merges into the user's OWN settings file.

That file is UTF-8 JSON (RFC 8259) that other tools and the developer wrote.
The merge used to read and write it with the platform's locale codepage. On
Windows that is cp1252, so a non-ASCII value either raised UnicodeDecodeError
(a byte cp1252 has no character for, such as 0x9d) or was decoded as mojibake
and written back that way: the merge silently corrupted the developer's
settings. On a UTF-8 POSIX host it was always fine, which is why nothing caught it.

Real files, real merge. Mutation: drop encoding="utf-8" from the read in
write_claude_config and the first case goes red on Windows.
"""

import json

from tina4_python.mcp import McpServer


def _settings(tmp_path):
    return tmp_path / ".claude" / "settings.json"


def test_a_non_ascii_value_survives_the_merge_unchanged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _settings(tmp_path).parent.mkdir()
    # U+201D encodes to e2 80 9d: 0x9d is undefined in cp1252.
    original = {"permissions": {"allow": ["Read(~/café/“notes”/**)"]},
                "note": "✓ 中文"}
    _settings(tmp_path).write_bytes(json.dumps(original, ensure_ascii=False).encode("utf-8"))

    McpServer("/__dev/mcp", name="Tina4 Dev").write_claude_config(port=7145)

    merged = json.loads(_settings(tmp_path).read_bytes().decode("utf-8"))
    assert merged["permissions"] == original["permissions"]
    assert merged["note"] == original["note"]
    assert merged["mcpServers"]["tina4-dev"]["url"] == "http://localhost:7145/__dev/mcp"


def test_a_fresh_settings_file_is_valid_utf8_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    McpServer("/__dev/mcp", name="Tina4 Dev").write_claude_config(port=7146)
    merged = json.loads(_settings(tmp_path).read_bytes().decode("utf-8"))
    assert merged["mcpServers"]["tina4-dev"]["url"] == "http://localhost:7146/__dev/mcp"
