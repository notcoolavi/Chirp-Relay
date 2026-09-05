"""
Functional test: starts the real server in a thread, then drives it with
raw sockets (simulating clients without needing a Tkinter display) to
verify: handshake, duplicate username rejection, broadcast, framing of
multiple messages in one recv(), and disconnect notifications.
"""
import socket
import sys
import threading
import time

sys.path.insert(0, "server")
sys.path.insert(0, "client")

from server import ChatServer
import protocol as proto

HOST = "127.0.0.1"
PORT = 5099


def recv_messages(sock, buf, count, timeout=3):
    sock.settimeout(timeout)
    got = []
    while len(got) < count:
        raw = sock.recv(4096)
        if not raw:
            break
        got.extend(buf.feed(raw))
    return got


def main():
    server = ChatServer(host=HOST, port=PORT)
    t = threading.Thread(target=server.start, daemon=True)
    t.start()
    time.sleep(0.5)

    # --- Client A connects ---
    a = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    a.connect((HOST, PORT))
    a.sendall(proto.encode_message(proto.build_message("connect", username="Alice")))
    buf_a = proto.MessageBuffer()
    reply = recv_messages(a, buf_a, 1)[0]
    assert reply["type"] == "system", f"Expected system welcome, got {reply}"
    print("PASS: Alice connected, got welcome:", reply["message"])

    # --- Client B connects ---
    b = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    b.connect((HOST, PORT))
    b.sendall(proto.encode_message(proto.build_message("connect", username="Bob")))
    buf_b = proto.MessageBuffer()
    reply_b = recv_messages(b, buf_b, 1)[0]
    assert reply_b["type"] == "system"
    print("PASS: Bob connected, got welcome:", reply_b["message"])

    # Alice should have received a "Bob joined" system message
    joined = recv_messages(a, buf_a, 1)[0]
    assert joined["type"] == "system" and "Bob joined" in joined["message"], joined
    print("PASS: Alice notified of Bob joining:", joined["message"])

    # --- Duplicate username rejected ---
    c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    c.connect((HOST, PORT))
    c.sendall(proto.encode_message(proto.build_message("connect", username="Alice")))
    buf_c = proto.MessageBuffer()
    reply_c = recv_messages(c, buf_c, 1)[0]
    assert reply_c["type"] == "error", reply_c
    print("PASS: duplicate username rejected:", reply_c["message"])
    time.sleep(0.2)
    # server should have closed the socket
    assert c.recv(10) == b"", "expected connection closed after rejected duplicate username"
    print("PASS: server closed socket after rejected handshake")

    # --- Broadcast + multi-message framing test ---
    # Send TWO messages from Bob in a single sendall() call, joined by \n,
    # to prove the buffer correctly splits multiple messages in one recv().
    msg1 = proto.encode_message(proto.build_message("message", username="Bob", message="Hi Alice"))
    msg2 = proto.encode_message(proto.build_message("message", username="Bob", message="How are you?"))
    b.sendall(msg1 + msg2)  # sent together on purpose

    received = recv_messages(a, buf_a, 2)
    assert len(received) == 2, f"expected 2 framed messages, got {received}"
    assert received[0]["message"] == "Hi Alice"
    assert received[1]["message"] == "How are you?"
    print("PASS: two messages sent in one TCP write were correctly framed:", [m["message"] for m in received])

    # --- Partial message test: send message in two pieces ---
    full = proto.encode_message(proto.build_message("message", username="Bob", message="split-test"))
    part1, part2 = full[:5], full[5:]
    b.sendall(part1)
    time.sleep(0.1)
    b.sendall(part2)
    received2 = recv_messages(a, buf_a, 1)
    assert received2[0]["message"] == "split-test", received2
    print("PASS: message split across two sendall() calls was correctly reassembled")

    # --- Empty / oversized message validation ---
    b.sendall(proto.encode_message(proto.build_message("message", username="Bob", message="")))
    err = recv_messages(b, buf_b, 1)[0]
    assert err["type"] == "error", err
    print("PASS: empty message rejected with error:", err["message"])

    long_msg = "x" * (proto.MAX_MESSAGE_LENGTH + 50)
    b.sendall(proto.encode_message(proto.build_message("message", username="Bob", message=long_msg)))
    err2 = recv_messages(b, buf_b, 1)[0]
    assert err2["type"] == "error", err2
    print("PASS: oversized message rejected with error:", err2["message"])

    # --- Disconnect notification ---
    b.sendall(proto.encode_message(proto.build_message("disconnect", username="Bob")))
    b.close()
    left = recv_messages(a, buf_a, 1)[0]
    assert left["type"] == "system" and "Bob left" in left["message"], left
    print("PASS: Alice notified of Bob leaving:", left["message"])

    a.close()
    server.shutdown()
    print("\nALL NETWORKING TESTS PASSED")


if __name__ == "__main__":
    main()
