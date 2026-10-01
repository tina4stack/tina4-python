# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""A request's save must not undo what another request did to the same session.

Every request loads its session when it starts and saves it when it ends
(``core/server.py``: one ``Session`` per request, ``start()`` then ``save()``).
The save used to write back the WHOLE snapshot loaded at the start. So a request
that was in flight across a logout put the logged-out session back the moment it
saved anything: ``destroy()``, ``clear()`` and ``regenerate()`` were all undone,
and so was a privilege change made with ``set()``. A copied session cookie
therefore outlived the logout that was meant to kill it.

The save now writes only this request's own changes onto the record as it is
stored NOW, and never re-creates a record that was removed after this request
loaded it.

Two ``Session`` objects over one store stand in for two concurrent requests,
exactly as the server builds them. Every outcome is read back through the
handler, never through the session under test.
"""

import hashlib
import json
import socket
import time

import pytest

from tina4_python.session import FileSessionHandler, Session
from tina4_python.session_handlers import RedisSessionHandler


@pytest.fixture
def store(tmp_path):
    return FileSessionHandler(str(tmp_path / "sessions"))


def _request(store, session_id=None):
    """What the server does at the start of a request: a fresh Session, started from the cookie."""
    session = Session(handler=store, ttl=300)
    session.start(session_id)
    return session


def _logged_in(store, **data):
    session = _request(store)
    session.set("user", "alice")
    for key, value in data.items():
        session.set(key, value)
    assert session.save()
    return session.session_id


class TestARequestInFlightDoesNotUndoALogout:
    """The slow request loaded user=alice, then another request ended the session."""

    def test_destroy_stays_destroyed(self, store):
        sid = _logged_in(store)
        slow = _request(store, sid)
        logout = _request(store, sid)
        logout.destroy()
        logout.save()

        slow.set("cart", "one item")
        assert slow.save()

        assert store.read(sid) == {}
        # The session has ended for the slow request too: no id, so no cookie for it.
        assert slow.session_id is None

    def test_clear_stays_cleared(self, store):
        sid = _logged_in(store)
        slow = _request(store, sid)
        logout = _request(store, sid)
        logout.clear()
        assert logout.save()

        slow.set("cart", "one item")
        slow.save()

        assert "user" not in store.read(sid)

    def test_regenerate_does_not_bring_the_old_id_back(self, store):
        sid = _logged_in(store)
        slow = _request(store, sid)
        login = _request(store, sid)
        new_id = login.regenerate()

        slow.set("cart", "one item")
        slow.save()

        assert store.read(sid) == {}
        assert store.read(new_id) == {"user": "alice"}

    def test_a_downgrade_made_with_set_stays_down(self, store):
        sid = _logged_in(store)
        slow = _request(store, sid)
        demote = _request(store, sid)
        demote.set("user", "nobody")
        assert demote.save()

        slow.set("cart", "one item")
        assert slow.save()

        assert store.read(sid) == {"user": "nobody", "cart": "one item"}

    def test_the_session_stays_ended_for_the_rest_of_the_slow_request(self, store):
        sid = _logged_in(store)
        slow = _request(store, sid)
        logout = _request(store, sid)
        logout.destroy()

        slow.set("cart", "one item")
        slow.save()
        slow.set("more", "after")
        slow.save()

        assert store.read(sid) == {}


def _users_stored(tmp_path):
    """The user of every session record on disk, read from the files themselves."""
    return [
        json.loads(path.read_text())["_data"].get("user")
        for path in sorted((tmp_path / "sessions").glob("*.json"))
    ]


class TestARegenerateInFlightDoesNotCarryAnEndedSession:
    """The slow request calls regenerate() at its end (a privilege change, an SSO callback)
    after another request ended or changed the session. What it loaded must not reach the
    new id."""

    def test_a_destroyed_session_stays_ended(self, store, tmp_path):
        sid = _logged_in(store)
        slow = _request(store, sid)
        _request(store, sid).destroy()

        assert slow.regenerate() is None
        assert slow.session_id is None
        assert "alice" not in _users_stored(tmp_path)

    def test_a_cleared_session_stays_cleared(self, store, tmp_path):
        sid = _logged_in(store)
        slow = _request(store, sid)
        logout = _request(store, sid)
        logout.clear()
        assert logout.save()

        slow.regenerate()

        assert "alice" not in _users_stored(tmp_path)

    def test_a_downgrade_is_carried_with_the_slow_requests_own_change(self, store):
        sid = _logged_in(store)
        slow = _request(store, sid)
        slow.set("cart", "one item")
        demote = _request(store, sid)
        demote.set("user", "nobody")
        assert demote.save()

        new_id = slow.regenerate()

        assert store.read(new_id) == {"user": "nobody", "cart": "one item"}
        assert store.read(sid) == {}

    def test_a_double_submitted_login_keeps_the_login_that_won(self, store, tmp_path):
        # Both requests carry the same pre-login cookie. The first to finish rotates the
        # id; the other must not mint a second, empty session whose cookie would replace it.
        anon = _request(store)
        anon.set("pending", "state")
        assert anon.save()
        first = _request(store, anon.session_id)
        second = _request(store, anon.session_id)

        second.set("user", "alice")
        winner = second.regenerate()
        first.set("user", "alice")
        first.save()

        assert first.regenerate() is None
        assert first.session_id is None
        assert store.read(winner) == {"pending": "state", "user": "alice"}
        assert _users_stored(tmp_path) == ["alice"]

    def test_a_double_submitted_login_in_the_documented_order_keeps_the_winner(self, store, tmp_path):
        # docs/python/09-sessions-cookies.md: regenerate(), then set the user.
        anon = _request(store)
        anon.set("pending", "state")
        assert anon.save()
        first = _request(store, anon.session_id)
        second = _request(store, anon.session_id)

        winner = second.regenerate()
        second.set("user", "alice")
        assert second.save()

        assert first.regenerate() is None
        first.set("user", "alice")
        first.save()

        assert first.session_id is None
        assert store.read(winner) == {"pending": "state", "user": "alice"}
        assert _users_stored(tmp_path) == ["alice"]

    def test_the_documented_login_stores_the_user_under_the_new_id(self, store):
        # docs/python/09-sessions-cookies.md: regenerate(), then set the user.
        anon = _request(store)
        anon.set("csrf", "token")
        assert anon.save()
        session = _request(store, anon.session_id)

        new_id = session.regenerate()
        session.set("user_id", 42)
        assert session.save()

        assert store.read(new_id) == {"csrf": "token", "user_id": 42}
        assert store.read(anon.session_id) == {}

    def test_regenerate_after_this_requests_own_destroy_still_starts_afresh(self, store):
        sid = _logged_in(store)
        session = _request(store, sid)
        session.destroy()

        new_id = session.regenerate()

        assert new_id and new_id != sid
        assert store.read(sid) == {}


class TestConcurrentRequestsKeepEachOthersChanges:
    def test_two_requests_setting_different_keys_both_persist(self, store):
        sid = _logged_in(store)
        first = _request(store, sid)
        second = _request(store, sid)
        first.set("theme", "dark")
        second.set("cart", "one item")
        assert first.save()
        assert second.save()

        assert store.read(sid) == {"user": "alice", "theme": "dark", "cart": "one item"}

    def test_a_key_another_request_deleted_stays_deleted(self, store):
        sid = _logged_in(store, mfa="verified")
        slow = _request(store, sid)
        other = _request(store, sid)
        other.delete("mfa")
        assert other.save()

        slow.set("cart", "one item")
        assert slow.save()

        assert store.read(sid) == {"user": "alice", "cart": "one item"}

    def test_clear_also_removes_keys_another_request_added(self, store):
        sid = _logged_in(store)
        logout = _request(store, sid)
        other = _request(store, sid)
        other.set("mfa", "verified")
        assert other.save()

        logout.clear()
        assert logout.save()

        assert store.read(sid) == {}

    def test_both_requests_changing_one_key_last_save_wins(self, store):
        sid = _logged_in(store)
        first = _request(store, sid)
        second = _request(store, sid)
        first.set("user", "bob")
        second.set("user", "carol")
        first.save()
        second.save()

        assert store.read(sid)["user"] == "carol"


def _stored_record(tmp_path, session_id):
    """The raw on-disk record for a session id, read straight from its file."""
    f = tmp_path / "sessions" / f"{hashlib.sha256(session_id.encode()).hexdigest()}.json"
    return json.loads(f.read_text())


class TestASaveStillWritesWhatTheRequestChanged:
    def test_a_read_only_request_moves_the_expiry_forward(self, store, tmp_path):
        # ADR-0087: expiry slides on activity. A request that only READ the
        # session still re-writes it on save(), re-stamping the backend deadline
        # to now + TTL, so a session times out after INACTIVITY, not a fixed
        # span after its last change. The stored data is left exactly as it was.
        sid = _logged_in(store)
        f = tmp_path / "sessions" / f"{hashlib.sha256(sid.encode()).hexdigest()}.json"

        record = json.loads(f.read_text())
        record["_expires"] = time.time() + 5  # about to expire
        f.write_text(json.dumps(record))

        session = _request(store, sid)  # ttl=300
        session.get("user")  # a request that touched nothing
        assert session.save()

        slid = _stored_record(tmp_path, sid)
        assert slid["_expires"] > time.time() + 200, "a read-only request must move the expiry forward"
        assert slid["_data"] == {"user": "alice"}, "the stored data must be unchanged"

    def test_a_value_changed_in_place_is_saved_with_the_next_set(self, store):
        sid = _logged_in(store, cart=["one item"])
        session = _request(store, sid)
        session.get("cart").append("two items")
        session.set("seen", True)
        assert session.save()

        assert store.read(sid)["cart"] == ["one item", "two items"]

    def test_a_new_session_is_written_whole(self, store):
        session = _request(store)
        session.set("user", "alice")
        session.set("theme", "dark")
        assert session.save()

        assert store.read(session.session_id) == {"user": "alice", "theme": "dark"}

    def test_a_second_save_writes_only_what_changed_since_the_first(self, store):
        sid = _logged_in(store)
        session = _request(store, sid)
        session.set("theme", "dark")
        assert session.save()
        other = _request(store, sid)
        other.set("user", "nobody")
        other.set("theme", "light")
        assert other.save()

        session.set("cart", "one item")
        assert session.save()

        assert store.read(sid) == {"user": "nobody", "theme": "light", "cart": "one item"}

    def test_a_new_sessions_later_save_does_not_bring_it_back_once_destroyed(self, store):
        session = _request(store)
        session.set("user", "alice")
        assert session.save()
        sid = session.session_id
        _request(store, sid).destroy()

        session.set("cart", "one item")
        session.save()

        assert store.read(sid) == {}

    def test_a_save_after_clear_and_a_save_merges_again(self, store):
        sid = _logged_in(store)
        session = _request(store, sid)
        session.clear()
        session.set("theme", "dark")
        assert session.save()
        other = _request(store, sid)
        other.set("mfa", "verified")
        assert other.save()

        session.set("cart", "one item")
        assert session.save()

        assert store.read(sid) == {"theme": "dark", "mfa": "verified", "cart": "one item"}

    def test_a_set_after_clear_and_a_save_is_still_stored(self, store):
        sid = _logged_in(store)
        session = _request(store, sid)
        session.clear()
        assert session.save()

        session.set("cart", "one item")
        assert session.save()

        assert store.read(sid) == {"cart": "one item"}

    def test_a_set_after_regenerating_an_emptied_session_is_still_stored(self, store):
        # The SSO callback: consume the pending state, regenerate, store the identity.
        anon = _request(store)
        anon.set("pending", "state")
        assert anon.save()
        session = _request(store, anon.session_id)
        session.delete("pending")
        new_id = session.regenerate()

        session.set("user", "alice")
        assert session.save()

        assert store.read(new_id) == {"user": "alice"}
        assert session.session_id == new_id

    def test_clear_then_set_in_one_request_writes_only_the_new_data(self, store):
        sid = _logged_in(store, theme="dark")
        session = _request(store, sid)
        session.clear()
        session.set("user", "bob")
        assert session.save()

        assert store.read(sid) == {"user": "bob"}

    def test_regenerate_carries_everything_to_the_new_id(self, store):
        sid = _logged_in(store, theme="dark")
        session = _request(store, sid)
        new_id = session.regenerate()

        assert store.read(new_id) == {"user": "alice", "theme": "dark"}
        assert store.read(sid) == {}


def _closed_tcp_port():
    """Bind a socket to get a free port, then close it: the kernel refuses a
    connection to that port, so a real client genuinely cannot reach it."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


class TestAStoreThatCannotBeReadAtSaveTime:
    def test_nothing_is_written_and_the_change_is_kept_for_a_retry(self, store):
        # No mock: the store becomes unreachable between start() and save() by
        # swapping in a REAL RedisSessionHandler pointed at a closed TCP port the
        # kernel really refuses (mirrors php/ruby/node). save() must report
        # failure, write nothing, and keep the change for a later retry.
        sid = _logged_in(store)
        session = _request(store, sid)
        session.set("cart", "one item")

        refused = RedisSessionHandler(host="127.0.0.1", port=_closed_tcp_port(), ttl=60)
        session._handler = refused
        assert session.save() is False

        # The real file store is untouched: nothing was written while the store
        # could not be read.
        assert store.read(sid) == {"user": "alice"}

        # Once the store answers again, the retained change is written.
        session._handler = store
        assert session.save()
        assert store.read(sid) == {"user": "alice", "cart": "one item"}
