"""
client.py - Networking layer for the ChirpRelay client.

This module knows nothing about Tkinter. It owns the socket, sends
outgoing messages, and runs a background thread that continuously
receives data and pushes fully-parsed protocol messages onto a
queue.Queue. The GUI (gui.py) polls that queue safely from the main
thread using Tkinter's after() method -- this is the standard safe
pattern for combining threads with Tkinter, since Tkinter widgets must
only ever be touched from the main thread.
"""

from __future__ import annotations

import queue
import socket
import threading
from typing import Optional

from protocol import (
    MessageBuffer,
    ProtocolError,
    build_message,
    encode_message,
    validate_message_text,
    validate_username,
)

RECV_BUFFER_SIZE = 4096
CONNECT_TIMEOUT = 5.0


class ConnectionError_(Exception):
    """Raised when connecting to the server fails for a known reason."""
    pass


class ChatClient:
    """
    Handles the TCP connection to the chat server.

    Usage:
        client = ChatClient(incoming_queue)
        client.connect(host, port, username)   # raises ConnectionError_ on failure
        client.send_chat_message("hello")
        client.disconnect()

    Every message the server sends is decoded and put onto
    `incoming_queue` as a dict, to be consumed by the GUI thread.
    """

    def __init__(self, incoming_queue: "queue.Queue[dict]"):
        self.incoming_queue = incoming_queue
        self.sock: Optional[socket.socket] = None
        self.username: Optional[str] = None
        self.connected = False
        self._recv_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    def connect(self, host: str, port: int, username: str) -> None:
        """
        Open a TCP connection, perform the username handshake, and start
        the background receive thread. Raises ConnectionError_ with a
        human-readable message on any failure.
        """
        username_error = validate_username(username)
        if username_error:
            raise ConnectionError_(username_error)

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(CONNECT_TIMEOUT)
        try:
            sock.connect((host, port))
        except (socket.timeout, OSError) as exc:
            raise ConnectionError_(f"Could not reach server at {host}:{port} ({exc})") from exc

        try:
            sock.sendall(encode_message(build_message("connect", username=username)))
            reply_buffer = MessageBuffer()
            sock.settimeout(CONNECT_TIMEOUT)
            reply = None
            while reply is None:
                raw = sock.recv(RECV_BUFFER_SIZE)
                if not raw:
                    raise ConnectionError_("Server closed the connection during handshake.")
                for msg in reply_buffer.feed(raw):
                    reply = msg
                    break
        except socket.timeout as exc:
            sock.close()
            raise ConnectionError_("Server did not respond in time.") from exc
        except OSError as exc:
            sock.close()
            raise ConnectionError_(f"Connection error: {exc}") from exc

        if reply["type"] == "error":
            sock.close()
            raise ConnectionError_(reply.get("message", "Server rejected the connection."))

        sock.settimeout(None)  # switch to blocking mode for the long-lived receive loop
        self.sock = sock
        self.username = username
        self.connected = True

        self._recv_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._recv_thread.start()

    def send_chat_message(self, text: str) -> Optional[str]:
        """Validate and send a chat message. Returns an error string on failure, else None."""
        error = validate_message_text(text)
        if error:
            return error
        if not self.connected or not self.sock:
            return "Not connected to a server."
        try:
            self.sock.sendall(encode_message(build_message("message", username=self.username, message=text)))
            return None
        except OSError as exc:
            self.connected = False
            self.incoming_queue.put(
                build_message("system", message="Connection to server lost.", username="")
            )
            return str(exc)

    def disconnect(self) -> None:
        """Gracefully tell the server we're leaving, then close the socket."""
        if self.sock and self.connected:
            try:
                self.sock.sendall(encode_message(build_message("disconnect", username=self.username)))
            except OSError:
                pass
        self.connected = False
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    # ------------------------------------------------------------------
    def _receive_loop(self) -> None:
        """Runs in a background thread for the lifetime of the connection."""
        buffer = MessageBuffer()
        sock = self.sock
        while self.connected and sock:
            try:
                raw = sock.recv(RECV_BUFFER_SIZE)
            except OSError:
                break
            if not raw:
                break  # server closed the connection
            try:
                messages = buffer.feed(raw)
            except ProtocolError:
                continue
            for msg in messages:
                self.incoming_queue.put(msg)

        # Loop ended: either we disconnected on purpose, or the connection died.
        was_connected = self.connected
        self.connected = False
        if was_connected:
            self.incoming_queue.put(
                build_message("system", message="Connection to server lost.", username="")
            )
