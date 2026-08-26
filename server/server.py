"""
server.py - TCP chat server for the ChirpRelay application.

Run this file to start the server:
    python server.py
    python server.py --host 0.0.0.0 --port 5000

Responsibilities:
    - Listen for incoming TCP connections.
    - Handle each connected client in its own thread.
    - Register/validate usernames (reject duplicates/invalid names).
    - Broadcast chat messages to all connected clients.
    - Announce when a user joins or leaves.
    - Clean up sockets and internal state when a client disconnects.
    - Never crash because of one misbehaving/disconnecting client.
"""

from __future__ import annotations

import argparse
import datetime
import socket
import sys
import threading
from typing import Dict, Optional

from protocol import (
    MAX_MESSAGE_LENGTH,
    MessageBuffer,
    ProtocolError,
    build_message,
    encode_message,
    validate_message_text,
    validate_username,
)

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 5000
RECV_BUFFER_SIZE = 4096
LISTEN_BACKLOG = 10


def timestamp() -> str:
    """Current local time as HH:MM:SS, used for server console + chat messages."""
    return datetime.datetime.now().strftime("%H:%M:%S")


def log(message: str) -> None:
    """Print a timestamped line to the server console."""
    print(f"[{timestamp()}] {message}", flush=True)


class ClientHandle:
    """Everything the server needs to know about one connected client."""

    def __init__(self, sock: socket.socket, address, username: str):
        self.sock = sock
        self.address = address
        self.username = username
        self.buffer = MessageBuffer()


class ChatServer:
    """
    Manages the listening socket, the set of connected clients, and all
    message broadcasting. Thread-safe: every access to self.clients is
    protected by self.lock, since multiple client-handler threads can
    read/write it concurrently.
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self.server_socket: Optional[socket.socket] = None
        self.clients: Dict[socket.socket, ClientHandle] = {}
        self.lock = threading.Lock()
        self._running = False

    # ------------------------------------------------------------------
    # Startup / shutdown
    # ------------------------------------------------------------------
    def start(self) -> None:
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Allow the port to be reused immediately after the server restarts,
        # instead of sitting in TIME_WAIT and refusing to bind.
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        log("[SERVER] Starting server...")
        try:
            self.server_socket.bind((self.host, self.port))
        except OSError as exc:
            log(f"[SERVER] ERROR: could not bind to {self.host}:{self.port} ({exc})")
            log("[SERVER] Is the port already in use by another process?")
            sys.exit(1)

        self.server_socket.listen(LISTEN_BACKLOG)
        self._running = True
        log(f"[SERVER] Listening on {self.host}:{self.port}")
        log("[SERVER] Press Ctrl+C to stop the server.")

        try:
            while self._running:
                try:
                    client_sock, address = self.server_socket.accept()
                except OSError:
                    # Happens when server_socket is closed during shutdown().
                    break
                thread = threading.Thread(
                    target=self._handle_client, args=(client_sock, address), daemon=True
                )
                thread.start()
        except KeyboardInterrupt:
            log("[SERVER] Ctrl+C received, shutting down...")
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self._running = False
        with self.lock:
            for handle in list(self.clients.values()):
                self._safe_close(handle.sock)
            self.clients.clear()
        if self.server_socket:
            try:
                self.server_socket.close()
            except OSError:
                pass
        log("[SERVER] Server stopped.")

    @staticmethod
    def _safe_close(sock: socket.socket) -> None:
        try:
            sock.close()
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Per-client handling (runs in its own thread)
    # ------------------------------------------------------------------
    def _handle_client(self, sock: socket.socket, address) -> None:
        username = self._perform_handshake(sock, address)
        if username is None:
            self._safe_close(sock)
            return

        handle = ClientHandle(sock, address, username)
        with self.lock:
            self.clients[sock] = handle

        log(f"[SERVER] {username} connected from {address[0]}:{address[1]}")
        self._broadcast_system(f"{username} joined the chat.", exclude=None)
        self._send(sock, build_message("system", message="Connected successfully.", username=username))

        try:
            self._receive_loop(handle)
        finally:
            self._remove_client(handle)

    def _perform_handshake(self, sock: socket.socket, address) -> Optional[str]:
        """
        Wait for the client's initial "connect" message containing a
        username, validate it, and reject the connection (with an "error"
        message) if it's invalid or already taken.
        Returns the accepted username, or None if the handshake failed.
        """
        sock.settimeout(10.0)  # don't let a silent connection hang forever
        buffer = MessageBuffer()
        try:
            while True:
                raw = sock.recv(RECV_BUFFER_SIZE)
                if not raw:
                    return None
                for msg in buffer.feed(raw):
                    if msg["type"] != "connect":
                        self._send(sock, build_message("error", message="Expected a connect message first."))
                        continue
                    username = (msg.get("username") or "").strip()
                    error = validate_username(username)
                    if error:
                        self._send(sock, build_message("error", message=error))
                        return None
                    with self.lock:
                        taken = any(h.username == username for h in self.clients.values())
                    if taken:
                        self._send(sock, build_message("error", message=f"Username '{username}' is already taken."))
                        return None
                    sock.settimeout(None)
                    return username
        except socket.timeout:
            log(f"[SERVER] Handshake timed out for {address}")
            return None
        except OSError:
            return None

    def _receive_loop(self, handle: ClientHandle) -> None:
        sock = handle.sock
        while True:
            try:
                raw = sock.recv(RECV_BUFFER_SIZE)
            except (ConnectionResetError, OSError):
                break
            if not raw:
                # Peer closed the connection cleanly.
                break

            try:
                messages = handle.buffer.feed(raw)
            except ProtocolError:
                self._send(sock, build_message("error", message="Malformed message ignored."))
                continue

            for msg in messages:
                self._process_message(handle, msg)

    def _process_message(self, handle: ClientHandle, msg: dict) -> None:
        msg_type = msg.get("type")

        if msg_type == "message":
            text = msg.get("message", "")
            error = validate_message_text(text)
            if error:
                self._send(handle.sock, build_message("error", message=error))
                return
            log(f"[SERVER] {handle.username}: {text}")
            outgoing = build_message(
                "message", username=handle.username, message=text, timestamp=timestamp()
            )
            # Excluded from the broadcast: the sender's own client already
            # displays its own message locally (see gui.py), so echoing it
            # back would just waste bandwidth.
            self._broadcast(outgoing, exclude=handle.sock)

        elif msg_type == "disconnect":
            # Client is telling us it's leaving on purpose; the receive
            # loop will exit naturally right after this (recv returns b"").
            return

        else:
            self._send(handle.sock, build_message("error", message=f"Unknown message type: {msg_type}"))

    def _remove_client(self, handle: ClientHandle) -> None:
        with self.lock:
            self.clients.pop(handle.sock, None)
        self._safe_close(handle.sock)
        log(f"[SERVER] {handle.username} disconnected")
        self._broadcast_system(f"{handle.username} left the chat.", exclude=None)

    # ------------------------------------------------------------------
    # Sending helpers
    # ------------------------------------------------------------------
    def _send(self, sock: socket.socket, msg_dict: dict) -> bool:
        """Send one message to one socket. Returns False (and swallows the
        error) if the socket is no longer writable -- the receive loop for
        that client will notice the dead connection and clean it up."""
        try:
            sock.sendall(encode_message(msg_dict))
            return True
        except OSError:
            return False

    def _broadcast(self, msg_dict: dict, exclude: Optional[socket.socket]) -> None:
        with self.lock:
            targets = [h.sock for h in self.clients.values() if h.sock is not exclude]
        for sock in targets:
            self._send(sock, msg_dict)

    def _broadcast_system(self, text: str, exclude: Optional[socket.socket]) -> None:
        self._broadcast(build_message("system", message=text, timestamp=timestamp()), exclude)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ChirpRelay - Server")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Host/IP to bind to (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port to listen on (default: {DEFAULT_PORT})")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = ChatServer(host=args.host, port=args.port)
    server.start()


if __name__ == "__main__":
    main()
