# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The CRUD component is CSP-clean under the strict default policy (ADR-0088).

The framework serves ``default-src 'self'``. A CSP nonce authorises a
``<script>``/``<style>`` ELEMENT but NEVER an inline ``on*=`` event-handler
attribute, so a button that wires its action with ``onclick="..."`` (or a form
with ``onsubmit="..."``) is dead under the policy — the handler never fires.
``components/crud.twig`` must therefore carry ZERO inline ``on*=`` attributes
and bind every action with ``addEventListener`` inside its already-nonce'd
``<script>``.

NO MOCKS: the tests read the REAL shipped ``components/crud.twig`` and render it
through a REAL ``Frond`` engine. The only things registered on the engine are
template helpers the component references (``RANDOM``, ``formToken``,
``nice_label``, ``detect_image``) — not stand-ins for any external collaborator
— so the assertions run against the exact bytes the framework ships and emits.
"""
import re
from pathlib import Path

import pytest

import tina4_python
from tina4_python.frond import Frond


TEMPLATES_DIR = Path(tina4_python.__file__).parent / "templates"
CRUD_TEMPLATE = TEMPLATES_DIR / "components" / "crud.twig"

# Matches an inline HTML event-handler attribute (onclick=, onsubmit=, …) but
# NOT a JS property assignment (``el.onclick = fn``), which is CSP-allowed.
_INLINE_HANDLER_ATTR = re.compile(r"""\son[a-z]+\s*=\s*["']""")

# A record whose text carries BOTH a single and a double quote, so the
# data-record JSON payload is exercised against attribute-quoting hazards.
RECORDS = [
    {"id": 1, "name": "Alice's \"Gadget\"", "email": "alice@example.com"},
    {"id": 2, "name": "Bob", "email": "bob@example.com"},
]
COLUMNS = [
    {"name": "id", "type": "integer"},
    {"name": "name", "type": "text"},
    {"name": "email", "type": "text"},
]


class _AttrDict(dict):
    """dict whose keys are also attribute-readable (Frond's ``a.b`` → ``a['b']``)."""

    def __getattr__(self, item):
        return self.get(item)


def _engine():
    """A real Frond engine pointed at the shipped framework templates, with the
    CRUD component's template helpers registered on THIS instance only."""
    engine = Frond(template_dir=str(TEMPLATES_DIR))
    engine.add_filter("nice_label", lambda v, *a: str(v).replace("_", " ").title())
    # detect_image reports "not an image" so the loops take the plain-value path.
    engine.add_filter(
        "detect_image",
        lambda v, *a: _AttrDict(content_type=None, content="", mime_type=""),
    )
    engine.add_filter("formToken", lambda v, *a: "test-token")
    engine.add_global("formToken", lambda *a, **k: "test-token")
    engine.add_global("RANDOM", lambda *a, **k: "RND123")
    return engine


def _render(card_view=True):
    # card_view=True renders the record rows (the card branch) so the per-row
    # Update/Delete buttons appear in the rendered output.
    data = {
        "table_name": "widget",
        "columns": COLUMNS,
        "records": RECORDS,
        "total_records": len(RECORDS),
        "options": {"limit": 10, "search": "", "card_view": card_view},
    }
    return _engine().render("components/crud.twig", data)


def test_shipped_template_source_has_no_inline_event_handler_attributes():
    """The whole shipped file — both the table AND card branches, the modal
    form, the pagination — carries zero inline on*= attributes. This is the
    mutation gate: restore any onclick=/onsubmit= and this turns red."""
    source = CRUD_TEMPLATE.read_text(encoding="utf-8")
    offenders = _INLINE_HANDLER_ATTR.findall(source)
    assert offenders == [], f"inline on*= attribute(s) in crud.twig: {offenders}"


def test_rendered_component_has_no_inline_event_handler_attributes():
    html = _render()
    offenders = _INLINE_HANDLER_ATTR.findall(html)
    assert offenders == [], f"inline on*= handler attribute(s) emitted: {offenders}"


def test_buttons_wire_their_actions_with_data_attributes():
    html = _render()
    # Create / Update / Delete are addressed by data-crud-action, not onclick.
    assert 'data-crud-action="add"' in html
    assert 'data-crud-action="edit"' in html
    assert 'data-crud-action="delete"' in html
    # Edit carries its per-row payload + index as data-*, delete carries the id.
    assert "data-record='" in html
    assert 'data-index="' in html
    assert 'data-id="' in html


def test_delegated_listener_is_wired_in_a_nonced_script():
    html = _render()
    assert "<script nonce=" in html  # the script that carries the wiring is nonce'd
    # A single delegated click listener on the persistent container dispatches
    # add / edit / delete and parses the row payload back out of data-record.
    assert "addEventListener('click'" in html
    assert "data-crud-action" in html
    assert "JSON.parse(button.dataset.record)" in html
    assert "addRecord" in html and "loadRecord" in html and "confirmDelete" in html
    # The modal form's native submit is stopped by a listener, not onsubmit=.
    assert "addEventListener('submit'" in html


def test_pagination_link_built_without_inline_onclick():
    html = _render()
    # The JS-generated pager uses createElement + addEventListener, never an
    # inline onclick= baked into innerHTML.
    assert "createElement('a')" in html
    assert "link.addEventListener('click'" in html
    assert "onclick=\"window[" not in html
    assert "li.innerHTML = `<a" not in html


def test_row_payload_is_json_safe_in_the_data_attribute():
    """The edit payload rides in data-record as JSON-safe text: a single quote
    in the data is escaped (\\u0027) so it can never break out of the
    single-quoted attribute into a new handler."""
    html = _render()
    assert "\\u0027" in html            # Alice's apostrophe, JSON-escaped
    assert "data-record='{" in html     # the JSON object opens inside the attr
    # The raw apostrophe must NOT appear unescaped inside data-record (would
    # otherwise close the attribute).
    assert "Alice's" not in html
