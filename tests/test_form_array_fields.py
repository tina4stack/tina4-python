# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""A bracketed form field (``tags[]``, ``user[name]``) arrives nested, however the form was sent.

A multi-select or checkbox group posts ``tags[]`` once per ticked value. The
multipart parser used to store each text field under its raw name, so
``tags[]=red`` then ``tags[]=blue`` arrived as ``{"tags[]": "blue"}`` - the
first value gone - while the same form urlencoded kept both under the raw key.
Both now nest the way PHP and tina4-ruby do: ``{"tags": ["red", "blue"]}``.

No mocks: every body is a real multipart or urlencoded body through
``Request.from_scope``. The query string is deliberately left flat (AutoCrud
reads ``filter[...]`` keys from it).
"""
from urllib.parse import urlencode

import pytest

from tina4_python.core.request import Request

BOUNDARY = "----Tina4FormArrayFields"


def _request(content_type, body, query=b""):
    scope = {
        "method": "POST", "path": "/form", "query_string": query,
        "headers": [
            (b"content-type", content_type.encode()),
            (b"content-length", str(len(body)).encode()),
        ],
    }
    return Request.from_scope(scope, body)


def _multipart(pairs, files=()):
    body = b""
    for name, value in pairs:
        body += (
            f"--{BOUNDARY}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode()
    for name, filename, content in files:
        body += (
            f"--{BOUNDARY}\r\n"
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + content + b"\r\n"
    body += f"--{BOUNDARY}--\r\n".encode()
    return _request(f"multipart/form-data; boundary={BOUNDARY}", body)


def _urlencoded(pairs):
    return _request("application/x-www-form-urlencoded", urlencode(pairs).encode())


FORMS = {
    "a checkbox group": ([("tags[]", "red"), ("tags[]", "blue")], {"tags": ["red", "blue"]}),
    "one ticked box": ([("tags[]", "red")], {"tags": ["red"]}),
    "a nested field": ([("user[name]", "Ann"), ("user[roles][]", "admin")],
                       {"user": {"name": "Ann", "roles": ["admin"]}}),
    "a list of records": ([("rows[][id]", "1"), ("rows[][id]", "2"), ("rows[][qty]", "5")],
                          {"rows": [{"id": "1"}, {"id": "2", "qty": "5"}]}),
    "a repeated plain name": ([("p", "1"), ("p", "2")], {"p": ["1", "2"]}),
    "plain fields alongside": ([("name", "x"), ("tags[]", "red")], {"name": "x", "tags": ["red"]}),
}


@pytest.mark.parametrize("form", FORMS, ids=list(FORMS))
def test_multipart_nests_every_value(form):
    pairs, expected = FORMS[form]
    assert _multipart(pairs).body == expected


@pytest.mark.parametrize("form", FORMS, ids=list(FORMS))
def test_urlencoded_nests_every_value(form):
    pairs, expected = FORMS[form]
    assert _urlencoded(pairs).body == expected


def test_a_conflicting_field_keeps_its_flat_key_and_the_rest_still_nest():
    pairs = [("a", "1"), ("a[b]", "2"), ("c", "3"), ("c[]", "4"), ("tags[]", "red")]
    for request in (_multipart(pairs), _urlencoded(pairs)):
        assert request.body == {"a": "1", "a[b]": "2", "c": "3", "c[]": "4", "tags": ["red"]}


def test_a_plain_name_after_its_list_joins_the_list():
    pairs = [("tags[]", "1"), ("tags", "2")]
    for request in (_multipart(pairs), _urlencoded(pairs)):
        assert request.body == {"tags": ["1", "2"]}


def test_a_form_past_the_field_limit_keeps_flat_keys():
    pairs = [("x[][k]", str(i)) for i in range(4097)]
    for request in (_multipart(pairs), _urlencoded(pairs)):
        assert request.body == {"x[][k]": [str(i) for i in range(4097)]}


def test_a_text_field_named_after_a_file_keeps_its_flat_key():
    request = _multipart([("photo[caption]", "hello"), ("tags[]", "red")],
                         files=[("photo", "a.txt", b"AAAA")])
    assert request.body == {"photo[caption]": "hello", "tags": ["red"]}
    assert request.files["photo"]["content"] == b"AAAA"


def test_a_name_past_the_length_limit_keeps_its_flat_key():
    name = "a[k][" + "x" * 2000 + "]"
    for request in (_multipart([(name, "v"), ("t[]", "1")]), _urlencoded([(name, "v"), ("t[]", "1")])):
        assert request.body == {name: "v", "t": ["1"]}


def test_nesting_past_the_depth_limit_keeps_flat_keys():
    name = "x" + "[k]" * 40
    for request in (_multipart([(name, "v")]), _urlencoded([(name, "v")])):
        assert request.body == {name: "v"}


def test_a_text_field_shaped_like_a_file_stays_in_the_body():
    request = _multipart([("doc[filename]", "report.pdf"), ("doc[content]", "x")])
    assert request.body == {"doc": {"filename": "report.pdf", "content": "x"}}
    assert request.files == {}


def test_files_still_arrive_beside_nested_fields():
    request = _multipart([("tags[]", "red"), ("tags[]", "blue")],
                         files=[("photo", "a.txt", b"AAAA")])
    assert request.body == {"tags": ["red", "blue"]}
    assert request.files["photo"]["content"] == b"AAAA"


def test_the_query_string_stays_flat():
    request = _request("application/x-www-form-urlencoded", b"",
                       query=b"filter%5Bname%5D=Ann&tags%5B%5D=a&tags%5B%5D=b")
    assert request.query == {"filter[name]": "Ann", "tags[]": ["a", "b"]}


def test_a_text_field_never_replaces_a_file_of_the_same_name():
    request = _multipart([("photo", "caption")], files=[("photo", "a.txt", b"AAAA")])
    assert request.files["photo"]["content"] == b"AAAA"
