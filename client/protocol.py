"""
protocol.py - Message protocol utilities for the ChirpRelay application.

WHY THIS FILE EXISTS
---------------------
TCP is a *stream* protocol: it guarantees bytes arrive in order, but it does
NOT guarantee that a single recv() call returns exactly one "message" that
was sent with a single sendall() call. A big message can be split across
several recv() calls, and several small messages can arrive together in one
recv() call. This module defines a simple framing scheme (newline-delimited
JSON) and a MessageBuffer class that correctly reconstructs complete
messages from a raw byte stream, regardless of how the OS chooses to
deliver them.

MESSAGE FORMAT
--------------
Every message is a single JSON object, followed by a single "\n" character.
Example (exactly what goes over the wire, including the trailing newline):

    {"type": "message", "username": "Alice", "message": "Hello!"}\n

Fields:
    type      (str, required) one of: "connect", "message", "system",
              "disconnect", "error"
    username  (str, optional) sender's username
    message   (str, optional) message text / payload
    timestamp (str, optional) "HH:MM:SS" string, added by sender or server

This file is intentionally identical in server/protocol.py and
client/protocol.py so both sides of the application speak the exact same
protocol without needing a shared installed package.
"""

import json
from typing import Optional, List

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------
MAX_USERNAME_LENGTH = 20
MAX_MESSAGE_LENGTH = 500

ENCODING = "utf-8"
DELIMITER = "\n"

# Valid message types understood by both client and server.
VALID_TYPES = {"connect", "message", "system", "disconnect", "error"}


class ProtocolError(Exception):
    """Raised when a message cannot be parsed or does not follow the protocol."""
    pass


def build_message(msg_type: str, username: str = "", message: str = "", **extra) -> dict:
    """
    Build a protocol message dict.

    Args:
        msg_type: one of VALID_TYPES.
        username: sender's username (may be empty for pure system messages).
        message:  message text / payload.
        **extra:  any additional fields (e.g. timestamp) to merge in.

    Returns:
        A dict ready to be passed to encode_message().
    """
    if msg_type not in VALID_TYPES:
        raise ProtocolError(f"Unknown message type: {msg_type!r}")
    payload = {"type": msg_type, "username": username, "message": message}
    payload.update(extra)
    return payload


def encode_message(msg_dict: dict) -> bytes:
    """Serialize a dict to a newline-terminated JSON byte string ready for sendall()."""
    try:
        json_str = json.dumps(msg_dict, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"Could not encode message as JSON: {exc}") from exc
    return (json_str + DELIMITER).encode(ENCODING)


def decode_message(raw_line: str) -> dict:
    """
    Parse a single line of text (no trailing newline required) into a
    protocol message dict. Raises ProtocolError if the line is not valid.
    """
    raw_line = raw_line.strip()
    if not raw_line:
        raise ProtocolError("Empty message received")
    try:
        data = json.loads(raw_line)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"Malformed JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ProtocolError("Message is not a JSON object")
    if "type" not in data or data["type"] not in VALID_TYPES:
        raise ProtocolError(f"Message missing/invalid 'type' field: {data.get('type')!r}")
    # Normalize optional fields so callers can always assume they exist.
    data.setdefault("username", "")
    data.setdefault("message", "")
    return data


class MessageBuffer:
    """
    Accumulates raw bytes received from a TCP socket and extracts complete,
    newline-delimited JSON messages from them.

    This correctly handles both problem cases inherent to TCP streams:
      1. A message arrives split across multiple recv() calls (partial data
         stays buffered until the newline shows up).
      2. Multiple messages arrive together in a single recv() call (the
         buffer is split on every newline found, in a loop).

    Usage:
        buf = MessageBuffer()
        while True:
            raw = sock.recv(4096)
            if not raw:
                break  # peer closed the connection
            for msg in buf.feed(raw):
                handle(msg)
    """

    def __init__(self):
        self._buffer = ""

    def feed(self, raw_bytes: bytes) -> List[dict]:
        """
        Add newly received bytes to the internal buffer and return a list
        of every complete message that can now be parsed out of it.
        Individual malformed lines are skipped so one bad message can't
        break the whole connection.
        """
        if not raw_bytes:
            return []
        self._buffer += raw_bytes.decode(ENCODING, errors="replace")

        messages = []
        while DELIMITER in self._buffer:
            line, self._buffer = self._buffer.split(DELIMITER, 1)
            line = line.strip()
            if not line:
                continue
            try:
                messages.append(decode_message(line))
            except ProtocolError:
                # Skip this single malformed message, keep the connection alive.
                continue
        return messages


def validate_username(username: str) -> Optional[str]:
    """Return a human-readable error string if the username is invalid, else None."""
    if username is None or not username.strip():
        return "Username cannot be empty."
    username = username.strip()
    if len(username) > MAX_USERNAME_LENGTH:
        return f"Username too long (max {MAX_USERNAME_LENGTH} characters)."
    if DELIMITER in username or "\r" in username:
        return "Username contains invalid characters."
    return None


def validate_message_text(text: str) -> Optional[str]:
    """Return a human-readable error string if the message text is invalid, else None."""
    if text is None or len(text) == 0:
        return "Message cannot be empty."
    if len(text) > MAX_MESSAGE_LENGTH:
        return f"Message too long (max {MAX_MESSAGE_LENGTH} characters)."
    return None
