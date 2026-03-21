# Tina4 MongoDB Session Handler — MongoDB via `pymongo` or raw wire protocol.
"""
MongoDB session handler. Uses `pymongo` if available, falls back to raw
MongoDB wire protocol (OP_MSG) over TCP sockets (zero dependencies).

Environment variables:
    TINA4_SESSION_MONGO_URL        — MongoDB URL (default: mongodb://localhost:27017)
    TINA4_SESSION_MONGO_DB         — database name (default: tina4)
    TINA4_SESSION_MONGO_COLLECTION — collection name (default: sessions)
    TINA4_SESSION_TTL              — session TTL in seconds (default: 1800)
"""
import json
import os
import socket
import struct
import time

from tina4_python.session import SessionHandler


class MongoDBSessionHandler(SessionHandler):
    """MongoDB-backed session handler with TTL support.

    Uses `pymongo` when available, raw MongoDB wire protocol (OP_MSG) as fallback.
    """

    def __init__(self, **config):
        mongo_url = config.get("url", os.environ.get("TINA4_SESSION_MONGO_URL", "mongodb://localhost:27017"))
        self._database = config.get("database", os.environ.get("TINA4_SESSION_MONGO_DB", "tina4"))
        self._collection_name = config.get("collection", os.environ.get("TINA4_SESSION_MONGO_COLLECTION", "sessions"))
        self._ttl = int(config.get("ttl", os.environ.get("TINA4_SESSION_TTL", "1800")))

        self._pymongo_client = None
        self._collection = None
        self._use_pymongo = False

        # Raw socket state
        self._socket: socket.socket | None = None
        self._request_id = 0
        self._host = "localhost"
        self._port = 27017

        # Parse host/port from URL
        self._parse_url(mongo_url)

        # Try pymongo first
        try:
            import pymongo
            self._pymongo_client = pymongo.MongoClient(mongo_url)
            db = self._pymongo_client[self._database]
            self._collection = db[self._collection_name]
            self._use_pymongo = True
        except ImportError:
            pass

    def _parse_url(self, url: str):
        """Extract host and port from a MongoDB URL."""
        clean = url
        if clean.startswith("mongodb://"):
            clean = clean[len("mongodb://"):]
        # Strip auth and path
        if "@" in clean:
            clean = clean.split("@", 1)[1]
        if "/" in clean:
            clean = clean.split("/", 1)[0]
        if ":" in clean:
            parts = clean.split(":")
            self._host = parts[0]
            try:
                self._port = int(parts[1])
            except (ValueError, IndexError):
                pass
        else:
            self._host = clean

    # ── SessionHandler Interface ─────────────────────────────────

    def read(self, session_id: str) -> dict:
        """Read session data by session ID."""
        if self._use_pymongo:
            doc = self._collection.find_one({"_id": session_id})
            if doc is None:
                return {}
            # Check TTL
            last_accessed = doc.get("last_accessed", 0)
            if self._ttl > 0 and time.time() - last_accessed > self._ttl:
                self.destroy(session_id)
                return {}
            return doc.get("data", {})
        else:
            self._ensure_connected()
            ns = f"{self._database}.{self._collection_name}"
            result = self._find_one(ns, {"_id": session_id})
            if result is None:
                return {}
            last_accessed = result.get("last_accessed", 0)
            if self._ttl > 0 and time.time() - last_accessed > self._ttl:
                self.destroy(session_id)
                return {}
            return result.get("data", {})

    def write(self, session_id: str, data: dict, ttl: int = 0):
        """Write session data."""
        now = time.time()
        if self._use_pymongo:
            self._collection.update_one(
                {"_id": session_id},
                {"$set": {"data": data, "last_accessed": now}},
                upsert=True,
            )
        else:
            self._ensure_connected()
            ns = f"{self._database}.{self._collection_name}"
            doc = {"_id": session_id, "data": data, "last_accessed": now}
            self._upsert(ns, {"_id": session_id}, doc)

    def destroy(self, session_id: str):
        """Delete a session."""
        if self._use_pymongo:
            self._collection.delete_one({"_id": session_id})
        else:
            self._ensure_connected()
            ns = f"{self._database}.{self._collection_name}"
            self._delete_one(ns, {"_id": session_id})

    def gc(self, max_lifetime: int):
        """Garbage-collect expired sessions."""
        cutoff = time.time() - max_lifetime
        if self._use_pymongo:
            self._collection.delete_many({"last_accessed": {"$lt": cutoff}})
        else:
            self._ensure_connected()
            ns = f"{self._database}.{self._collection_name}"
            self._delete_many(ns, {"last_accessed": {"$lt": cutoff}})

    def close(self):
        """Close the connection."""
        if self._use_pymongo:
            if self._pymongo_client:
                self._pymongo_client.close()
        else:
            self._close_raw()

    # ── Raw MongoDB Wire Protocol (OP_MSG) ───────────────────────

    def _ensure_connected(self):
        if self._socket is None:
            self._connect_raw()

    def _connect_raw(self):
        self._socket = socket.create_connection((self._host, self._port), timeout=10)
        self._socket.settimeout(30)

    def _close_raw(self):
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None

    def _command(self, cmd: dict) -> dict:
        """Send an OP_MSG command and read the response."""
        self._request_id += 1
        bson_cmd = self._encode_bson(cmd)

        # OP_MSG: flagBits(4) + sectionKind(1) + BSON
        sections = struct.pack("<I", 0) + struct.pack("<B", 0) + bson_cmd

        # Header: length(4) + requestID(4) + responseTo(4) + opCode(4)
        total_length = 16 + len(sections)
        header = (
            struct.pack("<I", total_length)
            + struct.pack("<I", self._request_id)
            + struct.pack("<I", 0)
            + struct.pack("<I", 2013)  # OP_MSG
        )

        self._socket.sendall(header + sections)
        return self._read_response()

    def _read_response(self) -> dict:
        header_data = self._recv_exact(16)
        msg_len = struct.unpack("<I", header_data[:4])[0]
        remaining = msg_len - 16
        payload = self._recv_exact(remaining)
        # Skip flagBits(4) + sectionKind(1)
        bson_data = payload[5:]
        return self._decode_bson(bson_data)

    def _recv_exact(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = self._socket.recv(n - len(data))
            if not chunk:
                raise RuntimeError("Connection closed while reading MongoDB data")
            data += chunk
        return data

    def _find_one(self, namespace: str, filter_doc: dict) -> dict | None:
        parts = namespace.split(".", 1)
        result = self._command({
            "find": parts[1],
            "filter": filter_doc,
            "limit": 1,
            "$db": parts[0],
        })
        docs = result.get("cursor", {}).get("firstBatch", [])
        return docs[0] if docs else None

    def _upsert(self, namespace: str, filter_doc: dict, doc: dict):
        parts = namespace.split(".", 1)
        self._command({
            "update": parts[1],
            "updates": [{"q": filter_doc, "u": doc, "upsert": True}],
            "$db": parts[0],
        })

    def _delete_one(self, namespace: str, filter_doc: dict):
        parts = namespace.split(".", 1)
        self._command({
            "delete": parts[1],
            "deletes": [{"q": filter_doc, "limit": 1}],
            "$db": parts[0],
        })

    def _delete_many(self, namespace: str, filter_doc: dict):
        parts = namespace.split(".", 1)
        self._command({
            "delete": parts[1],
            "deletes": [{"q": filter_doc, "limit": 0}],
            "$db": parts[0],
        })

    # ── Minimal BSON Encoder/Decoder ─────────────────────────────

    def _encode_bson(self, doc: dict) -> bytes:
        body = b""
        for key, value in doc.items():
            body += self._encode_bson_element(str(key), value)
        body += b"\x00"
        return struct.pack("<I", len(body) + 4) + body

    def _encode_bson_element(self, key: str, value) -> bytes:
        ckey = key.encode("utf-8") + b"\x00"

        if value is None:
            return b"\x0a" + ckey

        if isinstance(value, bool):
            return b"\x08" + ckey + (b"\x01" if value else b"\x00")

        if isinstance(value, int):
            if -2147483648 <= value <= 2147483647:
                return b"\x10" + ckey + struct.pack("<i", value)
            return b"\x12" + ckey + struct.pack("<q", value)

        if isinstance(value, float):
            return b"\x01" + ckey + struct.pack("<d", value)

        if isinstance(value, str):
            encoded = value.encode("utf-8")
            return b"\x02" + ckey + struct.pack("<I", len(encoded) + 1) + encoded + b"\x00"

        if isinstance(value, dict):
            encoded = self._encode_bson(value)
            return b"\x03" + ckey + encoded

        if isinstance(value, (list, tuple)):
            indexed = {str(i): v for i, v in enumerate(value)}
            encoded = self._encode_bson(indexed)
            return b"\x04" + ckey + encoded

        # Fallback: convert to string
        s = str(value).encode("utf-8")
        return b"\x02" + ckey + struct.pack("<I", len(s) + 1) + s + b"\x00"

    def _decode_bson(self, data: bytes) -> dict:
        pos = [0]
        return self._decode_bson_document(data, pos)

    def _decode_bson_document(self, data: bytes, pos: list) -> dict:
        doc_len = struct.unpack("<I", data[pos[0]:pos[0] + 4])[0]
        pos[0] += 4
        end = pos[0] + doc_len - 5

        doc = {}
        while pos[0] < end:
            bson_type = data[pos[0]]
            pos[0] += 1

            key_end = data.index(b"\x00", pos[0])
            key = data[pos[0]:key_end].decode("utf-8")
            pos[0] = key_end + 1

            doc[key] = self._decode_bson_value(data, pos, bson_type)

        pos[0] += 1  # skip terminator
        return doc

    def _decode_bson_value(self, data: bytes, pos: list, bson_type: int):
        if bson_type == 0x01:  # double
            val = struct.unpack("<d", data[pos[0]:pos[0] + 8])[0]
            pos[0] += 8
            return val

        if bson_type == 0x02:  # string
            length = struct.unpack("<I", data[pos[0]:pos[0] + 4])[0]
            pos[0] += 4
            val = data[pos[0]:pos[0] + length - 1].decode("utf-8")
            pos[0] += length
            return val

        if bson_type == 0x03:  # document
            return self._decode_bson_document(data, pos)

        if bson_type == 0x04:  # array
            doc = self._decode_bson_document(data, pos)
            return list(doc.values())

        if bson_type == 0x08:  # boolean
            val = data[pos[0]] != 0
            pos[0] += 1
            return val

        if bson_type == 0x0a:  # null
            return None

        if bson_type == 0x10:  # int32
            val = struct.unpack("<i", data[pos[0]:pos[0] + 4])[0]
            pos[0] += 4
            return val

        if bson_type == 0x12:  # int64
            val = struct.unpack("<q", data[pos[0]:pos[0] + 8])[0]
            pos[0] += 8
            return val

        return None
