"""Real-time collaboration mount for Tina4.

A zero-dependency control plane for building Slack/Teams-class tools:

- **calls** (Phase 1): a WebRTC signalling relay + self-describing ICE-config
  endpoint. Media is peer-to-peer (mesh) by default; Tina4 carries no media, it
  only relays the offer/answer/ICE handshake. An SFU (e.g. LiveKit) drops in
  later via ``RtcMediaBackend`` with no route changes.
- **chat**: persistent channels + messages (framework-owned ORM models), a
  secured chat WebSocket with live presence / typing / read receipts, and a
  history endpoint for catch-up-on-reconnect.
- **files** (slice 3): uploads through a pluggable ``StorageBackend``.

Paths are NOT hardcoded: ``realtime()`` uses convention defaults, everything is
overridable via ``prefix``, and the client discovers the resolved paths from the
config endpoint so client and server never drift.

Usage (in app.py, before run())::

    from tina4_python.realtime import realtime
    realtime()                                   # calls only, convention defaults
    realtime(features=["calls", "chat"])         # add persistent chat
    realtime(prefix="/api/collab", features=[...])  # relocate the whole surface

Env vars:
- ``TINA4_RTC_BACKEND``   media backend name (default ``mesh``; ``livekit`` later)
- ``TINA4_RTC_STUN_URLS`` comma-separated STUN URLs (default a public STUN server)
- ``TINA4_RTC_TURN_URL``  comma-separated TURN URLs (enables TURN when set with the secret)
- ``TINA4_RTC_TURN_SECRET`` coturn ``use-auth-secret`` shared secret (ephemeral creds)
- ``TINA4_RTC_TURN_TTL``  ephemeral TURN credential lifetime in seconds (default 3600)
"""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone

from tina4_python.core.router import Router
from tina4_python.debug import Log

DEFAULT_STUN = "stun:stun.l.google.com:19302"


def ice_servers() -> list:
    """Build the ICE server list from the environment.

    Always includes STUN. Adds a TURN entry with time-limited credentials
    (coturn ``use-auth-secret`` scheme: ``username = <expiry-epoch>``,
    ``credential = base64(HMAC-SHA1(secret, username))``) when both
    ``TINA4_RTC_TURN_URL`` and ``TINA4_RTC_TURN_SECRET`` are set.
    """
    stun = os.getenv("TINA4_RTC_STUN_URLS", DEFAULT_STUN)
    servers = [{"urls": [u.strip() for u in stun.split(",") if u.strip()]}]

    turn_url = os.getenv("TINA4_RTC_TURN_URL")
    secret = os.getenv("TINA4_RTC_TURN_SECRET")
    if turn_url and secret:
        ttl = int(os.getenv("TINA4_RTC_TURN_TTL", "3600"))
        username = str(int(time.time()) + ttl)
        credential = base64.b64encode(
            hmac.new(secret.encode(), username.encode(), hashlib.sha1).digest()
        ).decode()
        servers.append({
            "urls": [u.strip() for u in turn_url.split(",") if u.strip()],
            "username": username,
            "credential": credential,
        })
    return servers


class RtcMediaBackend:
    """Media-plane strategy.

    ``mesh`` (the default) is pure peer-to-peer: ``mint_join`` returns ``None``
    because there is no media server to authenticate against. An SFU backend
    (Phase 2) returns a join token the client presents to the SFU.
    """

    name = "mesh"

    def mint_join(self, room: str, identity: str):
        return None

    def ice_servers(self) -> list:
        return ice_servers()


class MeshBackend(RtcMediaBackend):
    """Default zero-dependency backend: browsers connect peer-to-peer."""
    name = "mesh"


def _select_backend(media):
    if media is not None:
        return media
    name = os.getenv("TINA4_RTC_BACKEND", "mesh").lower()
    # Phase 1 ships only mesh. An unknown name falls back to mesh rather than
    # failing boot; the LiveKit backend lands in Phase 2.
    if name == "mesh":
        return MeshBackend()
    return MeshBackend()


def _rtc_key(room: str) -> str:
    # Namespace signalling rooms so they never collide with chat channels
    # sharing the same WebSocket manager.
    return f"rtc:{room}"


def _chat_key(channel) -> str:
    return f"chat:{channel}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _identity(auth) -> str | None:
    """Extract a stable user identity from a verified JWT payload.

    Chat expects one of ``user_id`` / ``sub`` / ``id`` in the token. Returns a
    string (identities round-trip as strings so an int id and a UUID both work)
    or ``None`` when the connection is unauthenticated.
    """
    if not isinstance(auth, dict):
        return None
    for claim in ("user_id", "sub", "id"):
        if auth.get(claim) is not None:
            return str(auth[claim])
    return None


async def _maybe_await(value):
    """Await ``value`` if it is awaitable, else return it as-is.

    Lets the ``authorize`` hook be either a plain function or a coroutine.
    """
    if asyncio.iscoroutine(value) or isinstance(value, asyncio.Future):
        return await value
    return value


def _default_authorize(identity: str, channel_id) -> bool:
    """Membership guard: the user must be a member of the channel.

    The secure default. Override with ``realtime(authorize=...)`` for custom
    rules (e.g. open public channels to any authenticated user).
    """
    from tina4_python.realtime.models import ChannelMember
    try:
        return ChannelMember.count("channel_id = ? AND user_id = ?",
                                   [channel_id, identity]) > 0
    except Exception as exc:
        Log.error(f"realtime chat authorize check failed: {exc}")
        return False


def _ensure_chat_tables() -> bool:
    """Create the framework-owned chat tables (engine-aware, idempotent).

    Non-fatal: if no database is bound yet, log an actionable hint and return
    False so boot continues (chat routes still register and surface the error
    at query time) rather than taking the whole app down.
    """
    try:
        from tina4_python.realtime.models import CHAT_MODELS
        for model in CHAT_MODELS:
            model.create_table()
        return True
    except Exception as exc:
        Log.error(
            "realtime chat could not create its tables "
            f"({exc}). Chat needs a bound database -- call bind_database(db) "
            "or set TINA4_DATABASE_URL before realtime(features=[...\"chat\"])."
        )
        return False


def realtime(prefix: str = "", *, media: RtcMediaBackend = None,
             authorize=None, storage=None, features=None) -> dict:
    """Mount the real-time collaboration surface and return the resolved paths.

    :param prefix: mount the whole surface under this path (default: root).
    :param media: an :class:`RtcMediaBackend`; defaults to the env-selected
        backend (``mesh`` in Phase 1).
    :param authorize: membership guard ``authorize(identity, channel_id) -> bool``
        (sync or async) for the ``chat`` feature; defaults to a ChannelMember
        check. ``identity`` is the string user id from the JWT.
    :param storage: a StorageBackend for the ``files`` feature (slice 3).
    :param features: which surfaces to enable. Any of ``"calls"``, ``"chat"``,
        ``"files"``. Default ``["calls"]``.
    :returns: the resolved path map, also served from the config endpoint so the
        client can discover it.
    """
    features = features or ["calls"]
    p = "/" + prefix.strip("/") if prefix.strip("/") else ""
    backend = _select_backend(media)
    guard = authorize or _default_authorize

    # Chat and files both persist through the framework-owned chat models.
    if "chat" in features or "files" in features:
        _ensure_chat_tables()

    async def _authorized(identity, channel_id) -> bool:
        """Shared membership guard for chat channels and file access."""
        if identity is None:
            return False
        return bool(await _maybe_await(guard(identity, channel_id)))

    paths = {"backend": backend.name}
    if "calls" in features:
        paths["config"] = f"{p}/api/rtc/config"
        paths["signalling"] = f"{p}/ws/rtc"
    if "chat" in features:
        paths.setdefault("config", f"{p}/api/rtc/config")
        paths["chat"] = f"{p}/ws/chat"
        paths["messages"] = f"{p}/api/channels"
    if "files" in features:
        paths.setdefault("config", f"{p}/api/rtc/config")
        paths["files"] = f"{p}/api/files"

    # ── Self-describing bootstrap: the client fetches this instead of
    #    hardcoding any URL, so moving `prefix` moves the client too. ──
    if "config" in paths:
        async def rtc_config(request, response):
            body = {"backend": backend.name}
            if "calls" in features:
                body["iceServers"] = backend.ice_servers()
                body["signalling"] = paths["signalling"] + "/{room}"
            if "chat" in features:
                body["chat"] = paths["chat"] + "/{channel}"
                body["messages"] = paths["messages"] + "/{id}/messages"
            if "files" in features:
                body["files"] = paths["files"]
            return response(body)

        Router.get(paths["config"], rtc_config)

    # ── calls: WebRTC signalling relay (mesh) ──────────────────────────
    if "calls" in features:
        async def rtc_signalling(connection, event, data):
            room = connection.params.get("room", "")
            if not room:
                return
            key = _rtc_key(room)
            if event == "open":
                connection.join_room(key)
            elif event == "message":
                # Relay the raw signalling payload to the other peers in the
                # room. Tina4 never parses the SDP; peers filter by `to`.
                await connection.broadcast_to_room(key, data, exclude_self=True)

        Router.websocket(f"{paths['signalling']}/{{room}}", rtc_signalling)

    # ── chat: persistent channels + presence/typing/receipts ───────────
    if "chat" in features:

        def _roster(connection, key) -> list:
            mgr = getattr(connection, "_manager", None)
            if mgr is None:
                return []
            seen = {_identity(c.auth) for c in mgr.get_room_connections(key)}
            return sorted(u for u in seen if u)

        async def chat_ws(connection, event, data):
            raw_channel = connection.params.get("channel", "")
            try:
                channel_id = int(raw_channel)
            except (TypeError, ValueError):
                return  # framework channels are addressed by integer id
            identity = _identity(connection.auth)
            key = _chat_key(channel_id)

            if event == "open":
                if not await _authorized(identity, channel_id):
                    await connection.send_json({"type": "error",
                                                "error": "not a member of this channel"})
                    await connection.close()
                    return
                connection.join_room(key)
                # Tell the joiner who is already here, then announce the join.
                await connection.send_json({"type": "presence", "event": "roster",
                                            "users": _roster(connection, key)})
                await connection.broadcast_to_room(
                    key, json.dumps({"type": "presence", "event": "join",
                                     "user_id": identity}), exclude_self=True)
                return

            if event == "close":
                await connection.broadcast_to_room(
                    key, json.dumps({"type": "presence", "event": "leave",
                                     "user_id": identity}), exclude_self=True)
                return

            if event != "message":
                return

            # Re-check authorization on every inbound frame: membership can be
            # revoked mid-session, and we never trust a payload's identity.
            if not await _authorized(identity, channel_id):
                return
            try:
                payload = json.loads(data) if isinstance(data, str) else (data or {})
            except (ValueError, TypeError):
                return
            if not isinstance(payload, dict):
                return
            kind = payload.get("type", "message")

            if kind == "typing":
                await connection.broadcast_to_room(
                    key, json.dumps({"type": "typing", "user_id": identity}),
                    exclude_self=True)
                return

            if kind == "read":
                await _mark_read(channel_id, identity)
                await connection.broadcast_to_room(
                    key, json.dumps({"type": "read", "user_id": identity,
                                     "at": _now_iso()}), exclude_self=True)
                return

            if kind == "message":
                body = (payload.get("body") or "").strip()
                if not body:
                    return
                saved = _persist_message(channel_id, identity, body,
                                         payload.get("thread_id"))
                if saved is not None:
                    # Deliver to everyone in the room INCLUDING the sender, so
                    # the sender's optimistic message is reconciled with its
                    # server id + timestamp.
                    await connection.broadcast_to_room(
                        key, json.dumps({"type": "message", "message": saved}))

        chat_ws._secured = True  # a valid JWT is required on the upgrade
        Router.websocket(f"{paths['chat']}/{{channel}}", chat_ws)

        async def chat_history(request, response):
            # Read the {id} route param from request.params: both the ASGI
            # server and the in-process TestClient merge route params there,
            # and the TestClient calls handlers as handler(request, response).
            from tina4_python.auth import authenticate_request
            identity = _identity(authenticate_request(request.headers))
            try:
                channel_id = int(request.params.get("id"))
            except (TypeError, ValueError):
                return response({"error": "invalid channel id"}, 400)
            if not await _authorized(identity, channel_id):
                return response({"error": "forbidden"}, 403)
            return response(_history(channel_id, request.query))

        Router.get(f"{paths['messages']}/{{id}}/messages", chat_history,
                   auth_required=True)

    # ── files: permissioned upload / download via a StorageBackend ─────
    if "files" in features:
        from tina4_python.realtime.storage import select_storage
        store = select_storage(storage)

        async def files_upload(request, response):
            from tina4_python.auth import authenticate_request
            identity = _identity(authenticate_request(request.headers))
            channel_id = _form_value(request, "channel_id")
            try:
                channel_id = int(channel_id)
            except (TypeError, ValueError):
                return response({"error": "channel_id is required"}, 400)
            if not await _authorized(identity, channel_id):
                return response({"error": "forbidden"}, 403)
            upload = request.files.get("file")
            if not upload:
                return response({"error": "no file uploaded (field 'file')"}, 400)
            saved = _store_upload(store, channel_id, upload)
            saved["url"] = store.url(saved["key"]) or \
                f"{paths['files']}/{saved['key']}"
            return response(saved, 201)

        Router.post(f"{paths['files']}", files_upload, auth_required=True)

        async def files_download(request, response):
            from tina4_python.auth import authenticate_request
            identity = _identity(authenticate_request(request.headers))
            key = request.params.get("key")
            from tina4_python.realtime.models import Attachment
            rows = Attachment.where("storage_key = ?", [key], limit=1)
            if not rows:
                return response({"error": "not found"}, 404)
            att = rows[0]
            if not await _authorized(identity, att.channel_id):
                return response({"error": "forbidden"}, 403)
            # Backends with a direct URL (S3 presigned) redirect; local streams.
            direct = store.url(key)
            if direct:
                response.add_header("Location", direct)
                return response(b"", 302)
            data = store.get(key)
            if data is None:
                return response({"error": "not found"}, 404)
            response.add_header(
                "Content-Disposition",
                f'inline; filename="{att.filename or key}"')
            return response(data, 200,
                            content_type=att.mime or "application/octet-stream")

        Router.get(f"{paths['files']}/{{key}}", files_download, auth_required=True)

    return paths


def _form_value(request, name):
    """Read a non-file form field from a multipart body (or the query string)."""
    body = request.body
    if isinstance(body, dict) and name in body:
        return body[name]
    return request.query.get(name)


def _store_upload(store, channel_id, upload) -> dict:
    """Persist an uploaded blob + its Attachment row; return the metadata."""
    from tina4_python.realtime.storage import storage_key
    from tina4_python.realtime.models import Attachment
    filename = upload.get("filename") or "file"
    mime = upload.get("type") or "application/octet-stream"
    content = upload.get("content") or b""
    key = storage_key(filename)
    store.put(key, content, mime)
    att = Attachment(channel_id=channel_id, storage_key=key, filename=filename,
                     mime=mime, size=len(content))
    att.save()
    return {
        "id": att.id,
        "key": key,
        "filename": filename,
        "mime": mime,
        "size": len(content),
    }


# ── chat persistence helpers (kept out of the handler for readability) ──

def _persist_message(channel_id, identity, body, thread_id):
    """Insert a message row and return its JSON shape, or None on failure."""
    from tina4_python.realtime.models import Message
    try:
        thread = int(thread_id) if thread_id not in (None, "") else None
    except (TypeError, ValueError):
        thread = None
    created_at = _now_iso()
    msg = Message(channel_id=channel_id, user_id=identity, body=body,
                  thread_id=thread, created_at=created_at)
    if msg.save() is False:
        Log.error(f"realtime chat: failed to persist message in channel {channel_id}")
        return None
    return {
        "id": msg.id,
        "channel_id": channel_id,
        "user_id": identity,
        "body": body,
        "thread_id": thread,
        # Return the string we generated: the ORM coerces the saved instance's
        # DateTimeField to a datetime, which is not JSON-serializable.
        "created_at": created_at,
    }


async def _mark_read(channel_id, identity):
    """Advance the member's read cursor to now (read receipt)."""
    from tina4_python.realtime.models import ChannelMember
    try:
        # where() takes a WHERE fragment; select_one() takes full SQL.
        members = ChannelMember.where(
            "channel_id = ? AND user_id = ?", [channel_id, identity], limit=1)
        if members:
            member = members[0]
            member.last_read_at = _now_iso()
            member.save()
    except Exception as exc:
        Log.error(f"realtime chat: read-receipt update failed: {exc}")


def _history(channel_id, query) -> list:
    """Return messages for a channel, newest-first, paged by a `before` cursor.

    Query params: ``before`` (return messages with id < before) and ``limit``
    (default 50, capped at 200). Newest-first with a `before` cursor is the
    standard infinite-scroll-backwards shape a chat client pages with. Ordering
    and the limit are applied in SQL so we fetch the newest page, not the oldest.
    """
    from tina4_python.realtime.models import Message
    try:
        limit = int(query.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 200))
    before = query.get("before")

    clause, params = "channel_id = ?", [channel_id]
    if before not in (None, ""):
        try:
            params.append(int(before))
            clause += " AND id < ?"
        except (TypeError, ValueError):
            pass

    result = (Message.query()
              .where(clause, params)
              .order_by("id DESC")
              .limit(limit)
              .get())
    rows = result.records if hasattr(result, "records") else list(result)
    return [{
        "id": r["id"],
        "channel_id": r["channel_id"],
        "user_id": r["user_id"],
        "body": r["body"],
        "thread_id": r["thread_id"],
        "created_at": r["created_at"],
    } for r in rows]
