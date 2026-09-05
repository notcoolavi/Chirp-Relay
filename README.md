# ChirpRelay

A real-time, multi-client chat application built with **raw TCP sockets** and
**Tkinter** — no web frameworks, no external libraries. Built as a BTech CSE
networking project to demonstrate client-server architecture, concurrent
connection handling, and application-level protocol design over TCP.

---

## 1. Description

One server process accepts connections from many chat clients at once.
Each client has its own Tkinter window; when a user sends a message, the
server receives it and broadcasts it to every other connected client, in
real time, with no manual refresh. The project runs entirely on the
standard library and works both on a single machine (`localhost`) and
across multiple machines on the same LAN.

## 2. Features

- Multiple simultaneous clients, each handled on its own server-side thread
- Username registration with duplicate/invalid-name rejection
- Real-time broadcast of chat messages
- Join/leave system notifications (`[System] Bob joined the chat.`)
- Robust TCP message framing (newline-delimited JSON) that correctly
  handles partial reads and multiple messages arriving in one `recv()`
- Graceful handling of client crashes, unexpected disconnects, and server
  shutdown (`Ctrl+C`)
- Input validation: max username length, max message length, empty-message
  rejection, malformed-JSON protection
- Thread-safe shared state on the server (`threading.Lock`)
- Non-freezing GUI: networking runs on a background thread, results are
  handed to the GUI thread via `queue.Queue` + `tkinter.after()`
- Clean disconnect (window close, or explicit disconnect) with proper
  socket cleanup
- Timestamps on messages and a live server console log

## 3. Technologies Used

| Purpose             | Library      |
|----------------------|--------------|
| Networking           | `socket`     |
| Concurrency           | `threading`  |
| GUI                  | `tkinter`    |
| Message serialization | `json`      |
| Thread-safe handoff  | `queue`      |
| CLI args             | `argparse`   |

No Flask, Django, FastAPI, WebSockets, Socket.IO, or databases are used.

## 4. System Architecture

```
                ┌──────────────────┐
                │      SERVER      │
                │                  │
                │ TCP Socket Server │
                │ Client Management │
                │ Message Routing  │
                └────────┬─────────┘
                         │
          ┌──────────────┼──────────────┐
          │              │              │
          ▼              ▼              ▼
     ┌─────────┐    ┌─────────┐    ┌─────────┐
     │ Client 1│    │ Client 2│    │ Client 3│
     │ Tkinter │    │ Tkinter │    │ Tkinter │
     └─────────┘    └─────────┘    └─────────┘
```

- The server binds one listening socket and `accept()`s connections in a
  loop on the main thread.
- Every accepted connection is handed off to a new **daemon thread**
  (`ChatServer._handle_client`), so the accept loop is never blocked and
  many clients can be served concurrently.
- Each client thread performs a username handshake, then loops on
  `recv()`, feeding bytes into a `MessageBuffer` that reconstructs
  complete JSON messages, and finally calls `_broadcast()` to fan the
  message out to all other connected sockets.
- Access to the shared `self.clients` dictionary is always taken under
  `self.lock`, since multiple client threads read/write it concurrently.

## 5. How Socket Communication Works (Summary)

1. Server calls `socket()` → `bind()` → `listen()` → `accept()` in a loop.
2. Each client calls `socket()` → `connect()`.
3. Client sends a `connect` message with its desired username.
4. Server validates the username and replies with a `system` (success) or
   `error` message.
5. From then on, both sides `sendall()` newline-terminated JSON messages
   and read them off the stream with `recv()` + `MessageBuffer`.
6. When a socket's `recv()` returns `b""`, the peer has closed the
   connection; the server cleans up and notifies everyone else.

See **Part 12 — Networking Concepts Explained** below for a deeper,
concept-by-concept explanation.

## 6. Project Structure

```
chirp_relay/
│
├── server/
│   ├── server.py         # ChatServer: accept loop, per-client threads, broadcast
│   └── protocol.py       # Message framing/encoding/validation (server copy)
│
├── client/
│   ├── client.py         # ChatClient: socket connect/send/receive thread
│   ├── gui.py             # Tkinter GUI (run this to start a client)
│   └── protocol.py        # Message framing/encoding/validation (client copy)
│
├── test_networking.py     # Bonus: automated test of server logic over real sockets
├── README.md
├── requirements.txt
└── .gitignore
```

`protocol.py` is intentionally duplicated in both `server/` and `client/`
(byte-for-byte identical) rather than imported from a shared package. This
keeps each side runnable as a standalone folder with zero packaging setup
— you can `cd server && python server.py` and `cd client && python gui.py`
independently, which is simpler for a beginner project and for grading
than installing a local package.

## 7. Installation / Setup

Requirements: **Python 3.8+** (Tkinter is included with the standard
Windows/macOS installer). No `pip install` is required — see
`requirements.txt`.

```bash
git clone <your-repo-url>
cd chirp_relay
python --version   # confirm Python 3.8+
```

On Linux, if Tkinter is missing:
```bash
sudo apt install python3-tk
```

## 8. Running the Server

```bash
cd server
python server.py
```

By default it listens on `0.0.0.0:5000` (all network interfaces, port
5000). To customize:

```bash
python server.py --host 0.0.0.0 --port 6000
```

You should see:
```
[SERVER] Starting server...
[SERVER] Listening on 0.0.0.0:5000
[SERVER] Press Ctrl+C to stop the server.
```

Stop the server any time with `Ctrl+C`.

## 9. Running the Client

```bash
cd client
python gui.py
```

Enter the server IP, port, and a username, then click **Connect**.

## 10. Connecting Multiple Clients

Just run `python gui.py` again (in a new terminal, or on another
computer) with a different username. There is no limit on the number of
clients baked into the protocol; practically it's limited by
`socket.listen()`'s backlog and OS resources, both of which comfortably
handle dozens of clients for classroom/demo purposes.

## 11. LAN Setup

Run the server with `--host 0.0.0.0` (the default) so it listens on every
network interface, not just `127.0.0.1`. Then find the server machine's
LAN IP address:

**Windows:**
```
ipconfig
```
Look for "IPv4 Address" under your active adapter (e.g. `192.168.1.5`).

**Linux:**
```
hostname -I
```
or
```
ip addr show
```

On other computers on the **same Wi-Fi/LAN**, run the client and enter
that IP address (e.g. `192.168.1.5`) as the Server IP, with the same
port.

**Testing on the same computer:**
```
Server IP: 127.0.0.1
Port: 5000
```

**Testing over LAN:**
```
Server IP: 192.168.x.x   (the server machine's LAN IP)
Port: 5000
```

**Windows Firewall:** if another computer can't connect, Windows Firewall
may be blocking inbound connections to `python.exe` on that port. When
you first run the server, Windows usually shows an "Allow access" prompt
— accept it for Private networks. If it doesn't connect, check
*Windows Defender Firewall → Allow an app through firewall* and ensure
Python is allowed for Private networks, or temporarily disable the
firewall to confirm that's the cause.

## 12. Message Protocol

Newline-delimited JSON. Every message is a JSON object followed by `\n`:

```json
{"type": "message", "username": "Alice", "message": "Hello!"}
```

**Types:**

| type         | Direction        | Meaning                                   |
|--------------|-------------------|--------------------------------------------|
| `connect`    | client → server   | Handshake: register with a username        |
| `message`    | both directions   | A chat message                             |
| `system`     | server → client   | Join/leave notices, welcome message         |
| `disconnect` | client → server   | Client is leaving on purpose                |
| `error`      | server → client   | Invalid username, invalid message, etc.     |

**Why newline-delimited JSON, and why a `MessageBuffer`?**
TCP is a byte stream, not a message stream — a single `recv()` may return
half a message, or several messages concatenated together, depending on
network timing and buffering. `protocol.MessageBuffer` accumulates
incoming bytes and splits on `\n` in a loop, so it correctly reconstructs
exactly the messages that were sent, regardless of how the OS chose to
deliver the underlying bytes. This is validated directly in
`test_networking.py` (messages split across two `sendall()` calls, and
two messages sent in a single `sendall()` call, are both handled
correctly).

## 13. Testing Procedure

Run the automated networking test first (fast, no GUI needed):
```bash
python test_networking.py
```
It starts a real server, drives it with raw sockets, and asserts on the
handshake, duplicate-username rejection, broadcast, message framing
(partial + multiple-in-one), validation, and disconnect notifications.

Then perform these manual tests:

| # | Test | Steps | Expected result | What it verifies |
|---|------|-------|------------------|-------------------|
| 1 | Start server | `python server.py` | Console shows "Listening on 0.0.0.0:5000" | Server binds and listens correctly |
| 2 | Connect one client | Launch `gui.py`, connect as "Alice" | Chat screen appears, status shows "Connected as Alice" | Handshake and connection succeed |
| 3 | Connect two clients | Launch a second `gui.py` as "Bob" | Both windows show "Bob joined the chat." | Multi-client + broadcast of join events |
| 4 | Send messages | Alice sends "Hi", Bob sends "Hello" | Each appears instantly in both windows, own vs. other styled differently | Real-time broadcast + GUI update from background thread |
| 5 | Duplicate usernames | Try connecting a third client as "Alice" | Connection is rejected with an error, window stays on login screen | Server-side username uniqueness check |
| 6 | Disconnect one client | Close Bob's window | Alice sees "Bob left the chat.", server console logs disconnect | Clean disconnect handling |
| 7 | Reconnect | Relaunch Bob's client and connect again | Connects successfully, "Bob joined" shown again | Server correctly frees the username after disconnect |
| 8 | Close unexpectedly | Force-kill a client process (not the window's X button) | Server detects the dead socket on next `recv()`, removes the client, notifies others (may take a moment) | Server resilience to abrupt disconnects |
| 9 | Empty message | Try sending a blank message | Send is a no-op / blocked client-side; if forced server-side, an error is returned | Input validation |
| 10 | Long message | Paste text longer than 500 characters | Client shows a validation error, message is not sent | Message length limit enforcement |
| 11 | LAN test | Run server on Machine A, client on Machine B, same Wi-Fi, using A's LAN IP | Client connects and chats normally with Machine A's clients | Real cross-machine networking, not just loopback |

## 14. Common Errors and Solutions

| Error | Cause | Fix |
|-------|-------|-----|
| `OSError: [Errno 98] Address already in use` | Port already bound (previous server still running, or `TIME_WAIT`) | Wait a few seconds, use a different `--port`, or stop the other process. The server sets `SO_REUSEADDR` to minimize this. |
| Client shows "Could not reach server" | Wrong IP/port, server not running, or firewall blocking | Verify the server is running and printing "Listening...", double check IP/port, check firewall (see LAN section) |
| `ModuleNotFoundError: No module named 'tkinter'` (Linux) | Tkinter not installed | `sudo apt install python3-tk` |
| "Username is already taken" | Someone else (or a stale connection) is using that name | Pick a different username, or wait for the stale connection to time out/be detected |
| Messages not appearing on other machines | Server bound to `127.0.0.1` instead of `0.0.0.0`, or firewall | Restart server with `--host 0.0.0.0` (the default); check firewall rules |
| GUI freezes momentarily | Network hiccup while `connect()` is blocking on the login screen | Expected briefly during connection; the chat screen itself never blocks on I/O since receiving is fully backgrounded |

## 15. Limitations

- **No encryption.** Messages travel as plain-text JSON over TCP — this is
  an educational project, not a secure messaging platform. Anyone
  capturing network traffic (e.g. with Wireshark) can read all messages.
  Do not use this for sensitive communication.
- No persistent message history (nothing is saved to disk/DB).
- No authentication beyond a unique username for the session — anyone can
  claim any free username.
- No private messaging or chat rooms (broadcast only, single global room).
- No delivery guarantees beyond what TCP itself provides (i.e., no
  read receipts, no offline message queuing).
- Not designed to scale beyond a modest number of concurrent clients
  (thread-per-client is simple but not the most scalable model).

## 16. Future Improvements

- Private/direct messaging between two users
- Multiple chat rooms / channels
- Persistent message history (e.g. SQLite)
- User list panel showing who's currently online
- File transfer support
- Authentication with passwords (hashed, not plain text)
- TLS encryption (`ssl.wrap_socket` / `ssl.SSLContext`) for confidentiality
- Message delivery/read status indicators
- Typing indicators
- Online/offline/away status

---

# Part 12 (continued): Networking Concepts Explained

A concept-by-concept walkthrough for a BTech CSE student who knows Python
but is newer to networking.

- **Socket** — an endpoint for network communication, identified by an IP
  address + port. Think of it as a "phone" your program picks up to talk
  to another program.
- **TCP** — Transmission Control Protocol: a connection-oriented protocol
  that guarantees ordered, reliable, error-checked delivery of a byte
  stream between two endpoints. Chosen over UDP here because a chat app
  needs messages to arrive complete, in order, and without silently being
  dropped — UDP offers none of those guarantees.
- **Client-server architecture** — one central server that many clients
  connect to; the server coordinates communication (here: it's the only
  process every client talks to, and it relays messages between them).
- **IP address** — a numeric address identifying a machine on a network
  (e.g. `192.168.1.5`). `127.0.0.1` (loopback) always refers to "this same
  machine."
- **Port** — a number (0–65535) identifying a specific application/service
  on a machine, so multiple network programs can share one IP address
  without colliding. This project defaults to port `5000`.
- **`bind()`** — attaches the server's socket to a specific (host, port)
  pair, reserving it so the OS routes incoming traffic there.
- **`listen()`** — puts the socket into a passive, listening state and
  sets a backlog (max number of pending connections waiting to be
  `accept()`ed).
- **`accept()`** — blocks until a client connects, then returns a **new**
  socket object dedicated to that one client (the original listening
  socket keeps listening for more).
- **`connect()`** — used by the client to actively establish a connection
  to the server's (host, port).
- **`sendall()`** — sends all the given bytes, looping internally until
  everything is transmitted (unlike `send()`, which may send only part of
  the data in one call).
- **`recv()`** — reads up to N bytes currently available on the socket. It
  may return fewer bytes than a full logical message, or more than one
  message's worth at once — hence the need for framing (see below).
- **Threads** — independent units of execution within the same process.
  The server spawns one thread per connected client so it can `accept()`
  the next client immediately instead of being stuck servicing only one
  connection at a time.
- **Why multiple clients require concurrency** — a single-threaded server
  that calls a blocking `recv()` on one client would freeze and be unable
  to accept or service any other client until that call returns. Threads
  let many clients be read from "simultaneously" (in practice, the OS
  schedules them, but from the outside it looks concurrent).
- **Why TCP doesn't preserve message boundaries** — TCP's contract is
  "these bytes will arrive in order and intact," not "each `send()` maps
  to one `recv()`." The OS is free to buffer, split, or merge data as it
  sees fit for efficiency.
- **Why newline-delimited JSON** — it's a simple, human-readable framing
  scheme: read bytes until you see `\n`, and everything before it is one
  complete message. It avoids needing a fixed-length header or a custom
  binary protocol, which keeps the project approachable for beginners.
- **Why the Tkinter GUI needs a separate receiving mechanism** — Tkinter's
  `mainloop()` is single-threaded and must keep processing GUI events. A
  blocking `recv()` call on the same thread would freeze the whole window
  (no button clicks, no redraws) until data arrived.
- **Why `queue.Queue` and `after()`** — the background thread can safely
  put finished, parsed messages onto a thread-safe `queue.Queue`. The GUI
  thread then polls that queue periodically via `root.after(100, poll)`
  and only touches Tkinter widgets from within that main-thread callback
  — Tkinter widgets are not thread-safe to modify directly from another
  thread.
- **What happens when a client disconnects** — its `recv()` (on the
  server side) returns `b""` (or raises an exception for an abrupt
  disconnect), the server's per-client thread exits its receive loop,
  removes the client from the shared dictionary (under the lock), closes
  the socket, and broadcasts a "left the chat" system message to everyone
  else.

---

# Viva Questions and Answers

**1. Why did you use TCP instead of UDP?**
TCP guarantees ordered, reliable delivery and detects/retransmits lost
packets automatically. A chat application needs messages to arrive
complete and in the order they were sent — UDP provides no such
guarantee and would require reimplementing reliability ourselves.

**2. What is the difference between a server socket and a client socket?**
The server socket (from `bind()`+`listen()`) is passive — it only accepts
incoming connections and, via `accept()`, produces a new socket per
connected client. The client socket is active — it initiates the
connection with `connect()`. All actual data transfer with a given client
happens over the per-connection socket returned by `accept()`, not the
original listening socket.

**3. What does `bind()` do?**
It associates the server's socket with a specific IP address and port, so
the operating system knows to route incoming packets addressed to that
(IP, port) pair to this socket.

**4. What does `listen()` do?**
It transitions the socket into a state where it can accept incoming
connection requests, and sets a "backlog" — the maximum number of
pending, not-yet-accepted connections the OS will queue up.

**5. What does `accept()` return?**
A tuple `(client_socket, client_address)` — a brand-new socket object
dedicated to that one client, plus its `(ip, port)` address. The original
listening socket is unaffected and keeps accepting further connections.

**6. Why are threads required?**
Because `accept()` and `recv()` are blocking calls. Without threads, the
server could only ever talk to one client at a time — it would have to
finish (or fail) that conversation before it could `accept()` the next
one, or before it could read a message from a *different* client.

**7. What happens if two clients send messages simultaneously?**
Both messages arrive on their respective sockets and are processed on
their respective threads, essentially in parallel. The server's shared
state (`self.clients`) is protected by a `threading.Lock`, so updates to
it are serialized safely even if two threads try to touch it at the same
instant. Both messages still get broadcast to everyone — the only
ordering guarantee is that each individual client's messages arrive in
the order that client sent them (TCP's guarantee); interleaving between
*different* clients' messages is not strictly defined.

**8. What happens when a client disconnects?**
The client's `recv()` call on the server returns `b""` (a graceful close)
or raises a `ConnectionResetError`/`OSError` (an abrupt one). Either way,
the per-client thread's receive loop exits, the client is removed from
the shared dictionary under the lock, its socket is closed, and a "left
the chat" system message is broadcast to the remaining clients.

**9. Why can't we assume one `recv()` equals one message?**
TCP operates on a byte stream, not discrete messages. The OS can merge
several small writes into one delivered chunk, or split one large write
across several `recv()` calls, purely for its own buffering efficiency.
Relying on "one `recv()` = one message" works by accident under light
load and breaks under real network conditions.

**10. What is JSON?**
JavaScript Object Notation — a lightweight, human-readable, text-based
format for representing structured data (objects, arrays, strings,
numbers, booleans) that's easy to serialize/deserialize and is supported
natively by Python's `json` module.

**11. Why use message framing?**
Framing defines where one message ends and the next begins within a
continuous byte stream. Without it, a receiver has no reliable way to
know it has read a "complete" message versus a truncated one, especially
when multiple messages are sent back-to-back.

**12. What is `0.0.0.0`?**
A special "any address" value meaning "listen on all available network
interfaces on this machine" (loopback, Wi-Fi, Ethernet, etc.), rather
than restricting the server to one specific interface.

**13. What is `127.0.0.1`?**
The loopback address — it always refers to "this same machine." A client
connecting to `127.0.0.1` never actually touches the physical network; it
talks to a server running locally.

**14. What is a port?**
A 16-bit number (0–65535) that, combined with an IP address, identifies a
specific application endpoint on a machine, allowing multiple network
services to share one IP address.

**15. How does LAN communication work in this project?**
The server binds to `0.0.0.0` so it accepts connections on its actual
LAN-facing network interface, not just loopback. Other devices on the
same local network can then reach it using the server machine's LAN IP
(e.g. `192.168.1.5`) and the chosen port, as long as no firewall is
blocking that port.

**16. How would you add private messaging?**
Add a new message type, e.g. `"type": "private"`, carrying a `"to"`
field with the target username. On the server, instead of broadcasting to
all clients, look up the target username in `self.clients` and send the
message to only that one socket (plus optionally an echo back to the
sender).

**17. How would you add authentication?**
Extend the `connect` handshake to also carry a password, and check it
against stored (hashed, salted) credentials on the server before
accepting the username — e.g. using `hashlib` or a small local database
of username→password-hash pairs, rejecting with an `error` message on
mismatch.

**18. How would you add message encryption?**
Wrap the raw sockets in TLS using Python's `ssl` module
(`ssl.SSLContext` + `wrap_socket`), which encrypts everything sent over
the connection without changing the application-level JSON protocol at
all — the framing and message types stay exactly the same.

**19. What are the limitations of this implementation?**
No encryption, no persistence/history, no authentication beyond a unique
session username, single global room only (no private chat/rooms), and a
thread-per-client model that doesn't scale to very large numbers of
simultaneous connections as gracefully as an async/event-loop design
would.

**20. How would you scale this application?**
Replace the thread-per-client model with an asynchronous, event-driven
one (e.g. Python's `asyncio` with `asyncio.start_server`, or a
`selectors`-based event loop), which handles many more concurrent
connections with far less per-connection overhead than one OS thread
each. Beyond a single process, you could also run multiple server
instances behind a load balancer with a shared message bus (e.g. Redis
pub/sub) to fan out messages across instances.

**21. Why is `self.lock` (threading.Lock) needed on the server?**
Multiple client-handler threads read and write the shared `self.clients`
dictionary concurrently (adding on connect, removing on disconnect,
iterating over it to broadcast). Without a lock, two threads could
interleave their operations on that dictionary and corrupt it or crash
with a `RuntimeError: dictionary changed size during iteration`.

**22. Why does the client validate messages locally *and* the server validate them again?**
Client-side validation gives instant feedback without a network
round-trip. Server-side validation is the actual security boundary — a
malicious or buggy client could skip its own checks and send anything, so
the server can never trust client-side validation alone.

**23. What does `sendall()` do differently from `send()`?**
`send()` may transmit only part of the given bytes and returns how many
bytes it actually sent, leaving the caller to loop and send the rest.
`sendall()` does that looping internally and only returns once every byte
has been handed to the OS (or raises an exception on failure) — simpler
and safer for sending a complete message.

**24. Why is the server console logging useful here?**
It gives real-time visibility into connections, disconnections, and
message traffic without needing a separate monitoring tool — useful both
for debugging during development and for demonstrating that the server is
actually routing messages correctly during a viva/demo.
