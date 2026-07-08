"""Real-time collaboration mount for Tina4.

Phase 1 (calls plane): a zero-dependency WebRTC control surface. ``realtime()``
registers a signalling WebSocket relay plus a self-describing ICE-config endpoint.
Media is peer-to-peer (mesh) by default -- Tina4 carries no media, it only relays
the offer/answer/ICE handshake. The ``RtcMediaBackend`` interface lets an SFU
(e.g. LiveKit) drop in later (Phase 2) with no route changes.

Paths are NOT hardcoded: ``realtime()`` uses convention defaults, everything is
overridable via ``prefix``, and the client discovers the resolved paths from the
config endpoint so client and server never drift.

Usage (in app.py, before run())::

    from tina4_python.realtime import realtime
    realtime()                      # convention defaults
    realtime(prefix="/api/collab")  # relocate the whole surface

Env vars:
- ``TINA4_RTC_BACKEND``   media backend name (default ``mesh``; ``livekit`` in Phase 2)
- ``TINA4_RTC_STUN_URLS`` comma-separated STUN URLs (default a public STUN server)
- ``TINA4_RTC_TURN_URL``  comma-separated TURN URLs (enables TURN when set with the secret)
- ``TINA4_RTC_TURN_SECRET`` coturn ``use-auth-secret`` shared secret (ephemeral creds)
- ``TINA4_RTC_TURN_TTL``  ephemeral TURN credential lifetime in seconds (default 3600)
"""
import base64
import hashlib
import hmac
import os
import time

from tina4_python.core.router import Router

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


def _room_key(room: str) -> str:
    # Namespace signalling rooms so they never collide with other room users
    # (chat channels, etc.) sharing the same WebSocket manager.
    return f"rtc:{room}"


def realtime(prefix: str = "", *, media: RtcMediaBackend = None, features=None) -> dict:
    """Mount the real-time collaboration surface and return the resolved paths.

    :param prefix: mount the whole surface under this path (default: root).
    :param media: an :class:`RtcMediaBackend`; defaults to the env-selected backend
        (``mesh`` in Phase 1).
    :param features: which surfaces to enable (Phase 1: ``["calls"]``).
    :returns: the resolved path map, also served from the config endpoint so the
        client can discover it.
    """
    features = features or ["calls"]
    p = "/" + prefix.strip("/") if prefix.strip("/") else ""
    backend = _select_backend(media)

    paths = {
        "backend": backend.name,
        "config": f"{p}/api/rtc/config",
        "signalling": f"{p}/ws/rtc",
    }

    if "calls" in features:
        async def rtc_config(request, response):
            return response({
                "iceServers": backend.ice_servers(),
                "backend": backend.name,
                "signalling": paths["signalling"] + "/{room}",
            })

        async def rtc_signalling(connection, event, data):
            room = connection.params.get("room", "")
            if not room:
                return
            key = _room_key(room)
            if event == "open":
                connection.join_room(key)
            elif event == "message":
                # Relay the raw signalling payload to the other peers in the room.
                # Tina4 never parses the SDP; peers filter by the `to` field.
                await connection.broadcast_to_room(key, data, exclude_self=True)

        Router.get(paths["config"], rtc_config)
        Router.websocket(f"{paths['signalling']}/{{room}}", rtc_signalling)

    return paths
