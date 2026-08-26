# Realtime (WebRTC + collaboration) — `tina4_python.realtime`

Added in **3.13.57**. A zero-dependency control plane for building Slack/Teams-class tools:

- **calls** — a WebRTC **signalling relay** (mesh, peer-to-peer) + a self-describing ICE-config
  endpoint. Media is peer-to-peer by default; Tina4 carries no media — it only relays the
  offer/answer/ICE handshake and never parses the SDP. An SFU (e.g. LiveKit) drops in later via
  `RtcMediaBackend` with no route changes.
- **chat** — persistent channels + messages (framework-owned ORM models), a secured chat
  WebSocket with live presence / typing / read receipts, and a history endpoint for
  catch-up-on-reconnect.
- **files** — permissioned upload / download through a pluggable `StorageBackend`.

This pairs with the frontend **tina4-js `rtc` module** (the `rtcConfig()` helper fetches the
config endpoint so client and server never drift). Do the backend here; do the browser side in
tina4-js.

Source of truth: `tina4_python/realtime/__init__.py` (models in `realtime/models/`, storage in
`realtime/storage.py`).

---

## Mounting: `realtime(prefix="", *, media=None, authorize=None, storage=None, features=None)`

Call this once in `app.py` **before `run()`**. It registers the routes and returns the resolved
path map (also served from the config endpoint, so the client discovers paths and never hardcodes
a URL).

```python
from tina4_python.realtime import realtime

realtime()                                                           # calls only (default)
realtime(features=["calls", "chat"])                                 # add persistent chat
realtime(prefix="/api/collab", features=["calls", "chat", "files"])  # relocate the whole surface
```

| param | meaning |
|---|---|
| `prefix` | mounts the whole surface under `/<prefix>` (default: root). `prefix.strip("/")` → `/api/collab`. |
| `media` | an `RtcMediaBackend`. Defaults to the env-selected backend (`mesh` in Phase 1). |
| `authorize` | membership guard `authorize(identity, channel_id) -> bool` (sync **or** async) used by `chat`/`files`. Defaults to a `ChannelMember` membership check. `identity` is the **string** user id from the JWT. |
| `storage` | a `StorageBackend` for the `files` feature. Defaults to the env-selected store (`local`). |
| `features` | list; any of `"calls"`, `"chat"`, `"files"`. **Default `["calls"]`.** |

**Returns** the resolved path map (dict):

```
realtime()                                          → {'backend': 'mesh', 'config': '/api/rtc/config', 'signalling': '/ws/rtc'}
realtime(features=['calls','chat'])                 → {..., 'signalling': '/ws/rtc', 'chat': '/ws/chat', 'messages': '/api/channels'}
realtime(features=['chat'])                          → {'backend': 'mesh', 'config': '/api/rtc/config', 'chat': '/ws/chat', 'messages': '/api/channels'}
realtime(features=['files'])                         → {'backend': 'mesh', 'config': '/api/rtc/config', 'files': '/api/files'}
realtime(prefix='/api/collab', features=[...all])    → every path prefixed with /api/collab
```

Note: `config` is added by **any** enabled feature (`calls` sets it; `chat`/`files` use
`setdefault`). So even a chat-only mount exposes `/api/rtc/config`.

### What it wires (per feature)

| feature | routes registered | auth |
|---|---|---|
| any | `GET  {p}/api/rtc/config` → `rtc_config` | **public** (no auth) |
| `calls` | `WS   {p}/ws/rtc/{room}` → `rtc_signalling` | **public** (unauthenticated) |
| `chat` | `WS   {p}/ws/chat/{channel}` → `chat_ws` | **secured** — valid JWT required on upgrade (`chat_ws._secured = True`) |
| `chat` | `GET  {p}/api/channels/{id}/messages` → history | `auth_required=True` |
| `files` | `POST {p}/api/files` → upload | `auth_required=True` |
| `files` | `GET  {p}/api/files/{key}` → download | `auth_required=True` |

If `chat` or `files` is enabled, `_ensure_chat_tables()` runs at mount time (see Footguns).

---

## `GET /api/rtc/config` — `rtc_config`

Public bootstrap the frontend fetches (the tina4-js `rtcConfig()` helper) so client and server
never drift. Body is feature-gated (only keys for enabled features appear):

```jsonc
{
  "backend": "mesh",
  "iceServers": [ ...ice_servers()... ],      // calls
  "signalling": "/ws/rtc/{room}",             // calls
  "chat": "/ws/chat/{channel}",               // chat
  "messages": "/api/channels/{id}/messages",  // chat
  "files": "/api/files"                        // files
}
```

The `{room}`/`{channel}`/`{id}` are literal template tokens the client fills in.

---

## `ice_servers()`

Builds the ICE server list from env. **Always** includes a STUN entry. Adds a TURN entry with
time-limited coturn `use-auth-secret` credentials **only when both** `TINA4_RTC_TURN_URL` and
`TINA4_RTC_TURN_SECRET` are set.

TURN credential scheme: `username = str(int(time.time()) + ttl)`,
`credential = base64(HMAC_SHA1(secret, username))`.

```python
# no TURN env:
[{'urls': ['stun:stun.l.google.com:19302']}]

# TINA4_RTC_TURN_URL + TINA4_RTC_TURN_SECRET set:
[{'urls': ['stun:stun.l.google.com:19302']},
 {'urls': ['turn:turn.example.com:3478'], 'username': '1783546725', 'credential': 'ie7Mm...=='}]
```

### Env vars (module-level)

| var | default | effect |
|---|---|---|
| `TINA4_RTC_BACKEND` | `mesh` | media backend name; only `mesh` ships in Phase 1 (unknown → falls back to `mesh`, never fails boot). |
| `TINA4_RTC_STUN_URLS` | `stun:stun.l.google.com:19302` | comma-separated STUN URLs. |
| `TINA4_RTC_TURN_URL` | — | comma-separated TURN URLs; enables TURN when set with the secret. |
| `TINA4_RTC_TURN_SECRET` | — | coturn `use-auth-secret` shared secret (ephemeral creds). |
| `TINA4_RTC_TURN_TTL` | `3600` | ephemeral TURN credential lifetime (seconds). |

---

## Media backends

- **`RtcMediaBackend`** — the media-plane strategy interface. `name = "mesh"`;
  `mint_join(room, identity)` returns `None` (mesh has no media server to authenticate against);
  `ice_servers()` delegates to the module `ice_servers()`.
- **`MeshBackend(RtcMediaBackend)`** — the default zero-dependency backend; browsers connect
  peer-to-peer (mesh topology). `MeshBackend().mint_join(...) is None`.
- **`_select_backend(media)`** — if `media` is passed it wins; otherwise reads `TINA4_RTC_BACKEND`
  (default `mesh`). **Any unknown name falls back to `MeshBackend`** — it never fails boot. (An
  SFU/LiveKit backend that returns a real join token is the documented Phase-2 drop-in with no
  route changes.)

`media=` selects the backend: `realtime(media=MyBackend())` overrides the env entirely.

---

## Signalling: `rtc_signalling(connection, event, data)`

Registered at `WS {p}/ws/rtc/{room}`. **This is the framework's websocket handler convention**
(`Router.websocket`):

```python
async def handler(connection, event, data):
    # connection : WebSocketConnection
    # event      : "open" | "message" | "close"
    # data       : payload (str for "message", None for "open"/"close")
```

Signalling behavior (mesh relay):

- Reads `room = connection.params.get("room", "")`; empty room → returns (no-op).
- `event == "open"` → `connection.join_room("rtc:<room>")`.
- `event == "message"` → `await connection.broadcast_to_room("rtc:<room>", data, exclude_self=True)`
  — relays the **raw** payload to the other peers. Tina4 never parses the SDP; peers filter by a
  `to` field themselves.

Rooms are namespaced `rtc:<room>` so signalling rooms never collide with chat channels sharing the
same WebSocket manager (chat uses `chat:<channel>`).

`WebSocketConnection` surface used: `connection.params`, `connection.auth`,
`connection.join_room(name)`, `connection.broadcast_to_room(name, message, exclude_self=…)`,
`connection.send_json(data)`, `connection.close()`, and (internal)
`connection._manager.get_room_connections(key)`.

---

## Chat WebSocket: `WS {p}/ws/chat/{channel}` (secured)

Handler `chat_ws(connection, event, data)`. `chat_ws._secured = True`, so a **valid JWT is required
on the upgrade** — an unauthenticated upgrade is rejected by the router before the handler runs.

- Channel is addressed by **integer id**: `int(connection.params["channel"])`. Non-integer →
  handler returns silently.
- `identity = _identity(connection.auth)` (see Auth).
- Room key is `chat:<channel_id>`.

Event flow (all messages are JSON; broadcasts are `json.dumps(...)` strings):

| event / message `type` | server behavior |
|---|---|
| `open` | authorize; **fail →** send `{"type":"error","error":"not a member of this channel"}` then `close()`. **ok →** `join_room`, send caller the roster `{"type":"presence","event":"roster","users":[...]}`, then broadcast `{"type":"presence","event":"join","user_id":<id>}` (exclude self). |
| `close` | broadcast `{"type":"presence","event":"leave","user_id":<id>}` (exclude self). |
| message `typing` | broadcast `{"type":"typing","user_id":<id>}` (exclude self). |
| message `read` | advance the member's read cursor (`last_read_at = now`), broadcast `{"type":"read","user_id":<id>,"at":<iso>}` (exclude self). |
| message `message` | trim `body`; empty → ignored. Persist a `Message` row; on success broadcast `{"type":"message","message":<saved>}` to **everyone including the sender** (so the sender's optimistic message reconciles with its server `id` + `created_at`). |

The roster (`users`) is the sorted set of distinct identities currently in the room, derived from
each live connection's `auth`.

**Authorization is re-checked on every inbound frame**, not just on join — membership can be revoked
mid-session, and the server never trusts an identity carried in the payload.

`type` defaults to `"message"` when absent. Unknown `type` values are ignored.

Saved-message JSON shape (also returned by history):

```jsonc
{ "id": <int>, "channel_id": <int>, "user_id": "<str>", "body": "<str>",
  "thread_id": <int|null>, "created_at": "<iso8601>" }
```

`thread_id` is `null` for a top-level message, or the parent message id for a threaded reply.

---

## Chat history: `GET {p}/api/channels/{id}/messages` (auth_required)

Catch-up-on-reconnect endpoint. Handler `chat_history(request, response)`.

- Identity comes from `_identity(authenticate_request(request.headers))`. Invalid channel id →
  `400`; not authorized → `403`.
- Query params: `before` (return messages with `id < before`) and `limit` (default **50**, capped
  at **200**).
- Returns messages **newest-first** (`ORDER BY id DESC`, applied in SQL), the standard
  infinite-scroll-backwards shape. Each item has the saved-message JSON shape above.

---

## Files: upload / download (auth_required)

Enabled by `features=["files"]`; uses a `StorageBackend` (`storage=` arg or the env-selected store,
default `LocalStorage`).

### `POST {p}/api/files` — upload

- Multipart: file field **`file`**, plus form field **`channel_id`** (required, integer).
- Missing/invalid `channel_id` → `400`; not a channel member → `403`; no file → `400`.
- Stores the blob under an opaque, collision-free `storage_key` (uuid + sanitized extension — never
  a user-controlled path), inserts an `Attachment` row (metadata only), and responds **`201`** with:

```jsonc
{ "id": <int>, "key": "<storage_key>", "filename": "<str>", "mime": "<str>",
  "size": <int>, "url": "<direct url OR {files}/{key}>" }
```

`url` is `store.url(key)` when the backend exposes a direct URL (e.g. S3 presigned), else the app
download route `{files}/{key}`.

### `GET {p}/api/files/{key}` — download

- Looks up the `Attachment` by `storage_key`; missing → `404`. Authorizes against the attachment's
  `channel_id`; non-member → `403`.
- If the backend has a direct URL → **`302`** redirect (`Location`). Otherwise **streams the bytes**
  (`200`) with `Content-Disposition: inline; filename="…"` and
  `Content-Type = attachment.mime` (default `application/octet-stream`).

### Storage backends (`storage.py`)

`select_storage(storage=None)` resolves from the `storage=` arg or `TINA4_STORAGE_BACKEND`
(`local` default | `s3`). An `s3` backend that can't be built (boto3 missing / incomplete config)
**falls back to `LocalStorage`** with a warning — a real store, never a silent no-op.

| var | default | effect |
|---|---|---|
| `TINA4_STORAGE_BACKEND` | `local` | `local` \| `s3`. |
| `TINA4_STORAGE_DIR` | `data/rt_storage` | local filesystem directory. |
| `TINA4_STORAGE_URL` | — | S3 endpoint URL (S3-compatible / MinIO). |
| `TINA4_STORAGE_KEY` / `TINA4_STORAGE_SECRET` | — | S3 credentials. |
| `TINA4_STORAGE_BUCKET` | — | S3 bucket (required for S3). |
| `TINA4_STORAGE_REGION` | `us-east-1` | S3 region. |

`LocalStorage` resolves every key inside its root and rejects path traversal; `url()` returns `None`
(served by the permissioned download route). `S3Storage` returns a presigned GET URL from `url()` so
clients fetch large blobs straight from object storage.

---

## Auth & identity

- **`_identity(auth)`** — extracts a stable **string** user id from a verified JWT payload, trying
  claims **`user_id` → `sub` → `id`** in order; returns `None` if `auth` is not a dict or none of
  those claims are present. Identities round-trip as strings, so an int id, a UUID, or an email all
  work (`{"user_id":7}→"7"`, `{"sub":"abc"}→"abc"`, `{"foo":1}→None`).
- **WS identity** comes from `connection.auth` (the verified JWT payload the router attached on the
  secured upgrade). **HTTP identity** comes from `authenticate_request(request.headers)` inside each
  handler.
- **`_default_authorize(identity, channel_id)`** — the secure default guard: the user must be a
  member of the channel (`ChannelMember.count("channel_id=? AND user_id=?") > 0`). Any exception
  logs and returns `False` (deny).
- **`authorize=`** overrides it — pass `authorize(identity, channel_id) -> bool`, **sync or async**
  (a coroutine result is awaited). Use this to, e.g., open public channels to any authenticated
  user. The shared internal wrapper first returns `False` if `identity is None`, so an
  unauthenticated caller is always denied regardless of the guard.

---

## Data model (`realtime/models/`)

Framework-owned ORM models, all with the **`tina4_rt_`** table prefix (so they never collide with
an app's own tables). `CHAT_MODELS` lists them in dependency order (parents first):
`[Workspace, Channel, ChannelMember, Message, Attachment]`.

| model | table | key fields |
|---|---|---|
| `Workspace` | `tina4_rt_workspaces` | `id`, `name`, `created_at` |
| `Channel` | `tina4_rt_channels` | `id`, `workspace_id`→Workspace, `name`, `kind` (`public`\|`private`\|`dm`, default `public`), `created_at` |
| `ChannelMember` | `tina4_rt_channel_members` | `id`, `channel_id`→Channel, `user_id` (string, ≤128), `role` (`member`\|`admin`\|`owner`, default `member`), `last_read_at` (read cursor) |
| `Message` | `tina4_rt_messages` | `id`, `channel_id`→Channel, `user_id` (string), `body` (Text), `thread_id` (nullable parent id), `created_at`, `edited_at` (nullable) |
| `Attachment` | `tina4_rt_attachments` | `id`, `channel_id`→Channel, `message_id`→Message (nullable), `storage_key`, `filename`, `mime`, `size`, `thumb_key` (nullable) |

`user_id` is a **string** field everywhere so any JWT identity shape (int id / UUID / email) fits.
Tables are created on demand at mount time via each model's engine-aware `create_table()`.

---

## ⚠️ Footguns / hard rules

- **Chat needs a bound database — but a missing one does NOT crash boot.** With
  `features=["chat"|"files"]`, `_ensure_chat_tables()` runs at mount. If no DB is bound it **logs an
  ERROR and continues**: `realtime()` still returns the full path map and registers every route; the
  failure only resurfaces at query time. Bind a DB (`bind_database(db)` / `TINA4_DATABASE_URL`)
  **before** calling `realtime(features=[…])` or chat/history/files will error per-request while the
  app appears healthy.
- **The signalling WS (`/ws/rtc/{room}`) is PUBLIC** — `rtc_signalling` is not marked `_secured`, so
  anyone can join any room and receive relayed signalling frames. Only the **chat** WS is
  JWT-secured. Gate call access at the app layer if you need it.
- **The config endpoint (`/api/rtc/config`) is PUBLIC** and returns your ICE/TURN config, including
  freshly-minted ephemeral TURN credentials.
- **WS handler signature is `(connection, event, data)`** — event is `"open"`/`"message"`/`"close"`,
  data is `str` on message and `None` on open/close. This is the framework convention
  (`Router.websocket`), NOT `(connection, data, event)`.
- **Channels are addressed by integer id.** A non-integer `{channel}` makes the chat handler return
  silently (no error frame) — the client sees a socket that opens and does nothing.
- **Chat authorization is re-checked on every frame**, and identity is always taken from the verified
  token (`connection.auth` / `authenticate_request`), never from the message payload. A custom
  `authorize=` must be cheap — it runs on every inbound message.
- **A message with an empty/whitespace `body` is silently dropped** (no persist, no broadcast).
  `read`/`typing`/unknown types never persist anything.
- **Unknown `TINA4_RTC_BACKEND` silently falls back to mesh** — a typo won't error, you just get
  mesh. Only `mesh` exists in Phase 1; `mint_join` returns `None` (no SFU token).
