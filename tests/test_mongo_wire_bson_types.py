# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The zero-dependency MongoDB wire client must decode every reply a real
server sends - including replica-set replies.

THE BUG (found on the Mac testbed, 2026-09-24). The raw OP_MSG fallback in
tina4_python/session_handlers/mongodb_handler.py decoded only double, string,
document, array, boolean, null, int32 and int64. For any other BSON type it
returned None WITHOUT consuming the value's bytes, so the cursor landed inside
the value and every later field was garbage ("UnicodeDecodeError: 'utf-8'
codec can't decode byte 0xff").

It looked like "MongoDB 8 breaks the client", because the testbed's Mongo 8
was a replica-set member. It is not the version: captured on real servers,
standalone mongo:7 and mongo:8 answer update/find/delete with plain types
only, while a replica-set member (7 AND 8 alike) adds `electionId` (ObjectId),
`opTime` (Timestamp + int64), `$clusterTime` (Timestamp + BinData signature)
and `operationTime` (Timestamp) to every write reply. Every session write
against a replica set - which is what Atlas and most production deployments
are - failed.

Ruby's and Node's wire clients already decoded these types; this is the
Python port of that behaviour (ADR-0004, best implementation prevails).

Nothing here is mocked. The live test talks to the real server at
TINA4_TEST_MONGO_URI; the other two feed the decoder real bytes captured from
a real mongo:8 (8.3.11) replica-set member, which is a pure function over its
input - no collaborator is replaced.
"""

import datetime
import os
import socket
import struct
from urllib.parse import urlparse

import pytest

from tina4_python.session_handlers.mongodb_handler import MongoDBSessionHandler

MONGO_URI = os.environ.get("TINA4_TEST_MONGO_URI", "mongodb://127.0.0.1:27017")
_parsed = urlparse(MONGO_URI)
MONGO_HOST = _parsed.hostname or "127.0.0.1"
MONGO_PORT = _parsed.port or 27017

# The body document of a real OP_MSG reply to
#   update wire { q: {_id: "sess-1"}, u: {...}, upsert: true }
# from a mongo:8.3.11 replica-set member (rs0, one node), captured byte for byte.
REPLICA_SET_UPSERT_REPLY = bytes.fromhex(
    "12010000106e000100000007656c656374696f6e4964007fffffff000000000000000103"
    "6f7054696d65001c00000011747300020000009be4b46a12740001000000000000000004"
    "757073657274656400280000000330002000000010696e6465780000000000025f696400"
    "07000000736573732d31000000106e4d6f6469666965640000000000016f6b0000000000"
    "0000f03f0324636c757374657254696d65005800000011636c757374657254696d650002"
    "0000009be4b46a037369676e617475726500330000000568617368001400000000000000"
    "0000000000000000000000000000000000126b657949640000000000000000000000116f"
    "7065726174696f6e54696d6500020000009be4b46a00"
)
# Timestamp(1790239899, 2): seconds in the high 32 bits, increment in the low.
CAPTURED_TIMESTAMP = (1790239899 << 32) | 2


def _handler() -> MongoDBSessionHandler:
    # The constructor does no network I/O (ADR-0021), so this is free.
    return MongoDBSessionHandler(url=MONGO_URI, database="tina4_wire_types", collection="wire")


def test_a_replica_set_write_reply_decodes_every_field():
    reply = _handler()._decode_bson(REPLICA_SET_UPSERT_REPLY)

    assert reply["n"] == 1
    assert reply["ok"] == 1.0
    assert reply["nModified"] == 0
    assert reply["upserted"] == [{"index": 0, "_id": "sess-1"}]
    assert reply["electionId"] == "7fffffff0000000000000001"
    assert reply["opTime"] == {"ts": CAPTURED_TIMESTAMP, "t": 1}
    assert reply["operationTime"] == CAPTURED_TIMESTAMP
    assert reply["$clusterTime"]["clusterTime"] == CAPTURED_TIMESTAMP
    assert reply["$clusterTime"]["signature"] == {"hash": b"\x00" * 20, "keyId": 0}


def test_an_unknown_type_is_skipped_without_corrupting_the_fields_after_it():
    # {"inner": {"weird": <type 0x13 decimal128, 16 bytes>}, "ok": 1.0}
    # 0x13 is a type this codec does not decode. The value cannot be sized in
    # general, so the decoder must stop at the INNER document's boundary and
    # carry on with the outer document - never read the value's bytes as keys.
    weird = b"\x13weird\x00" + bytes(range(16))
    inner = (len(weird) + 5).to_bytes(4, "little") + weird + b"\x00"
    ok = b"\x01ok\x00" + struct.pack("<d", 1.0)
    body = b"\x03inner\x00" + inner + ok
    document = (len(body) + 5).to_bytes(4, "little") + body + b"\x00"

    decoded = _handler()._decode_bson(document)

    assert decoded["ok"] == 1.0
    assert set(decoded) == {"inner", "ok"}


def _require_mongo() -> None:
    try:
        with socket.create_connection((MONGO_HOST, MONGO_PORT), timeout=2):
            return
    except OSError:
        message = f"mongo not reachable at {MONGO_HOST}:{MONGO_PORT}"
        if os.environ.get("TINA4_REQUIRE_SERVICES"):
            pytest.fail(f"TINA4_REQUIRE_SERVICES is set but {message}")
        pytest.skip(message)


def test_the_wire_client_decodes_a_real_hello_reply():
    """Every mongod - standalone or replica set, 7 or 8 - answers `hello` with
    an ObjectId (topologyVersion.processId) and a UTC datetime (localTime)
    BEFORE maxBsonObjectSize. A decoder that mis-sizes either one never
    reaches maxBsonObjectSize intact."""
    _require_mongo()
    handler = _handler()
    try:
        handler._ensure_connected()
        reply = handler._command({"hello": 1, "$db": "admin"})
    finally:
        handler._close_raw()

    assert reply["ok"] == 1.0
    assert reply["maxBsonObjectSize"] == 16 * 1024 * 1024
    assert isinstance(reply["localTime"], datetime.datetime)
    drift = abs((reply["localTime"] - datetime.datetime.now(datetime.timezone.utc)).total_seconds())
    assert drift < 600, f"localTime decoded to {reply['localTime']!r}, not the server's clock"
    process_id = reply["topologyVersion"]["processId"]
    assert isinstance(process_id, str) and len(process_id) == 24
    int(process_id, 16)  # a hex ObjectId, not raw bytes
