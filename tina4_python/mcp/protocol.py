# JSON-RPC 2.0 codec for MCP protocol.
"""
Encode/decode JSON-RPC 2.0 messages used by the Model Context Protocol.
Zero dependencies — stdlib json only.
"""
import json

# Standard JSON-RPC 2.0 error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def encode_response(request_id, result):
    """Encode a successful JSON-RPC 2.0 response."""
    return json.dumps({
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }, default=str, separators=(",", ":"))


def encode_error(request_id, code: int, message: str, data=None):
    """Encode a JSON-RPC 2.0 error response."""
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return json.dumps({
        "jsonrpc": "2.0",
        "id": request_id,
        "error": error,
    }, default=str, separators=(",", ":"))


def encode_notification(method: str, params=None):
    """Encode a JSON-RPC 2.0 notification (no id)."""
    msg = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg, default=str, separators=(",", ":"))


def decode_request(data: str | bytes | dict) -> tuple:
    """Decode a JSON-RPC 2.0 request.

    Returns:
        (method, params, request_id) — request_id is None for notifications.

    Raises:
        ValueError: If the message is malformed.
    """
    if isinstance(data, (str, bytes)):
        try:
            msg = json.loads(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}") from e
    else:
        msg = data

    if not isinstance(msg, dict):
        raise ValueError("Message must be a JSON object")

    if msg.get("jsonrpc") != "2.0":
        raise ValueError("Missing or invalid jsonrpc version")

    method = msg.get("method")
    if not method or not isinstance(method, str):
        raise ValueError("Missing or invalid method")

    params = msg.get("params", {})
    request_id = msg.get("id")  # None for notifications

    return method, params, request_id
