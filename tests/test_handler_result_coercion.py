# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""A route handler's return value is coerced into a Response (#289).

Before the fix, ``_invoke_handler`` kept only a ``Response`` and dropped every
other return value, so ``return {"open": 3}`` answered an empty 200 with no
error and no log line. These exercise the real ``Response`` (no mocks) through
the real ``_coerce_handler_result`` — parity with PHP
(``Router::handlerResultToResponse``) and Ruby (``finalise_route_response``),
which already coerce.
"""
import json

from tina4_python.core.response import Response
from tina4_python.core.server import _coerce_handler_result


def _body(resp):
    return resp.content.decode()


# ── Positive: the values the developer guides promise become a response ──

def test_dict_return_becomes_json():
    resp = _coerce_handler_result({"open": 3}, Response())
    assert resp.content_type == "application/json"
    assert json.loads(_body(resp)) == {"open": 3}


def test_list_return_becomes_json():
    resp = _coerce_handler_result([1, 2, 3], Response())
    assert resp.content_type == "application/json"
    assert json.loads(_body(resp)) == [1, 2, 3]


def test_html_string_return_becomes_html():
    resp = _coerce_handler_result("<h1>hi</h1>", Response())
    assert resp.content_type.startswith("text/html")
    assert _body(resp) == "<h1>hi</h1>"


def test_plain_string_return_becomes_text():
    resp = _coerce_handler_result("just words", Response())
    assert resp.content_type.startswith("text/plain")
    assert _body(resp) == "just words"


def test_domain_object_return_becomes_json():
    class _Model:
        def to_dict(self):
            return {"id": 7, "name": "widget"}

    resp = _coerce_handler_result(_Model(), Response())
    assert resp.content_type == "application/json"
    assert json.loads(_body(resp)) == {"id": 7, "name": "widget"}


# ── Negative / boundary: Response passthrough and None left untouched ──

def test_response_return_is_passed_through_unchanged():
    built = Response()({"already": "built"}, 201)
    out = _coerce_handler_result(built, Response())
    assert out is built
    assert out.status_code == 201


def test_none_return_leaves_the_written_response_untouched():
    # The handler wrote onto `response` and returned nothing — that stands.
    written = Response()
    written("explicitly set", 418)
    out = _coerce_handler_result(None, written)
    assert out is written
    assert out.status_code == 418
    assert _body(out) == "explicitly set"


def test_dropped_dict_would_be_an_empty_body_without_the_fix():
    # Guards the regression directly: the coerced response must carry the dict,
    # never the empty default body a bare `return response` would have sent.
    resp = _coerce_handler_result({"x": 1}, Response())
    assert _body(resp) != ""
    assert json.loads(_body(resp)) == {"x": 1}
