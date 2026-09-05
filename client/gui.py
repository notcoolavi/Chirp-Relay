"""
gui.py - Tkinter GUI for the ChirpRelay client.

Run this file to launch the client application:
    python gui.py

Thread safety note:
    The ChatClient (client.py) receives network data on a background
    thread and puts parsed messages onto a queue.Queue. Tkinter widgets
    must only be touched from the main thread, so this GUI never reads
    the socket directly. Instead it polls the queue every 100ms using
    root.after(), and only updates widgets from that main-thread callback.
    This is the standard, safe way to combine sockets/threads with Tkinter.
"""

from __future__ import annotations

import queue
import tkinter as tk
from datetime import datetime
from tkinter import font as tkfont
from tkinter import messagebox, scrolledtext

from client import ChatClient, ConnectionError_
from protocol import MAX_MESSAGE_LENGTH, MAX_USERNAME_LENGTH

APP_NAME = "ChirpRelay"
POLL_INTERVAL_MS = 100
DEFAULT_PORT = "5000"
DEFAULT_HOST = "127.0.0.1"

# Simple color palette
COLOR_BG = "#f2f4f7"
COLOR_HEADER = "#2f3e46"
COLOR_HEADER_TEXT = "#ffffff"
COLOR_OWN = "#1a73e8"
COLOR_OTHER = "#202124"
COLOR_SYSTEM = "#8a8f98"
COLOR_ERROR = "#d93025"
COLOR_STATUS_OK = "#188038"
COLOR_STATUS_BAD = "#d93025"


class ChatGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_NAME)
        self.root.configure(bg=COLOR_BG)
        self.root.geometry("640x520")
        self.root.minsize(480, 420)

        self.incoming_queue: "queue.Queue[dict]" = queue.Queue()
        self.client = ChatClient(self.incoming_queue)

        self.status_var = tk.StringVar(value="Not connected")

        self._build_login_frame()
        self._build_chat_frame()  # built but not shown until connected

        self.login_frame.pack(fill="both", expand=True)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(POLL_INTERVAL_MS, self._poll_incoming_queue)

    # ------------------------------------------------------------------
    # Login / connection screen
    # ------------------------------------------------------------------
    def _build_login_frame(self) -> None:
        self.login_frame = tk.Frame(self.root, bg=COLOR_BG, padx=30, pady=30)

        title_font = tkfont.Font(family="Segoe UI", size=18, weight="bold")
        tk.Label(self.login_frame, text=APP_NAME, font=title_font, bg=COLOR_BG, fg=COLOR_HEADER).pack(pady=(0, 20))

        form = tk.Frame(self.login_frame, bg=COLOR_BG)
        form.pack(pady=10)

        label_font = tkfont.Font(family="Segoe UI", size=10)
        entry_font = tkfont.Font(family="Segoe UI", size=11)

        tk.Label(form, text="Server IP:", font=label_font, bg=COLOR_BG, anchor="w").grid(row=0, column=0, sticky="w", pady=6)
        self.host_entry = tk.Entry(form, font=entry_font, width=24)
        self.host_entry.insert(0, DEFAULT_HOST)
        self.host_entry.grid(row=0, column=1, pady=6, padx=(10, 0))

        tk.Label(form, text="Port:", font=label_font, bg=COLOR_BG, anchor="w").grid(row=1, column=0, sticky="w", pady=6)
        self.port_entry = tk.Entry(form, font=entry_font, width=24)
        self.port_entry.insert(0, DEFAULT_PORT)
        self.port_entry.grid(row=1, column=1, pady=6, padx=(10, 0))

        tk.Label(form, text="Username:", font=label_font, bg=COLOR_BG, anchor="w").grid(row=2, column=0, sticky="w", pady=6)
        self.username_entry = tk.Entry(form, font=entry_font, width=24)
        self.username_entry.grid(row=2, column=1, pady=6, padx=(10, 0))
        self.username_entry.focus_set()

        self.login_error_var = tk.StringVar(value="")
        tk.Label(self.login_frame, textvariable=self.login_error_var, fg=COLOR_ERROR, bg=COLOR_BG, wraplength=400).pack(pady=(10, 0))

        self.connect_button = tk.Button(
            self.login_frame, text="Connect", font=entry_font, bg=COLOR_HEADER, fg="white",
            activebackground="#3d5a66", activeforeground="white", relief="flat", padx=20, pady=8,
            command=self._on_connect_clicked,
        )
        self.connect_button.pack(pady=20)

        self.root.bind("<Return>", lambda e: self._on_connect_clicked() if self.login_frame.winfo_ismapped() else None)

    def _on_connect_clicked(self) -> None:
        host = self.host_entry.get().strip()
        port_str = self.port_entry.get().strip()
        username = self.username_entry.get().strip()

        if not host:
            self.login_error_var.set("Please enter a server IP address.")
            return
        if not port_str.isdigit():
            self.login_error_var.set("Port must be a number.")
            return
        port = int(port_str)
        if not (0 < port < 65536):
            self.login_error_var.set("Port must be between 1 and 65535.")
            return
        if len(username) > MAX_USERNAME_LENGTH:
            self.login_error_var.set(f"Username too long (max {MAX_USERNAME_LENGTH} characters).")
            return

        self.login_error_var.set("")
        self.connect_button.config(state="disabled", text="Connecting...")
        self.root.update_idletasks()

        try:
            self.client.connect(host, port, username)
        except ConnectionError_ as exc:
            self.login_error_var.set(str(exc))
            self.connect_button.config(state="normal", text="Connect")
            return

        self._show_chat_screen()

    # ------------------------------------------------------------------
    # Chat screen
    # ------------------------------------------------------------------
    def _build_chat_frame(self) -> None:
        self.chat_frame = tk.Frame(self.root, bg=COLOR_BG)

        # Header
        header = tk.Frame(self.chat_frame, bg=COLOR_HEADER, height=56)
        header.pack(fill="x")
        header.pack_propagate(False)
        header_font = tkfont.Font(family="Segoe UI", size=14, weight="bold")
        tk.Label(header, text=APP_NAME, font=header_font, bg=COLOR_HEADER, fg=COLOR_HEADER_TEXT).pack(side="left", padx=15)
        self.status_label = tk.Label(header, textvariable=self.status_var, font=("Segoe UI", 10),
                                      bg=COLOR_HEADER, fg=COLOR_STATUS_OK)
        self.status_label.pack(side="right", padx=15)

        # Chat area
        chat_area_frame = tk.Frame(self.chat_frame, bg=COLOR_BG, padx=10, pady=10)
        chat_area_frame.pack(fill="both", expand=True)

        self.chat_display = scrolledtext.ScrolledText(
            chat_area_frame, wrap="word", state="disabled", font=("Segoe UI", 10),
            bg="white", relief="flat", padx=10, pady=10,
        )
        self.chat_display.pack(fill="both", expand=True)
        self.chat_display.tag_config("own", foreground=COLOR_OWN, font=("Segoe UI", 10, "bold"))
        self.chat_display.tag_config("other", foreground=COLOR_OTHER, font=("Segoe UI", 10, "bold"))
        self.chat_display.tag_config("system", foreground=COLOR_SYSTEM, font=("Segoe UI", 9, "italic"))
        self.chat_display.tag_config("error", foreground=COLOR_ERROR, font=("Segoe UI", 9, "italic"))
        self.chat_display.tag_config("body", foreground=COLOR_OTHER, font=("Segoe UI", 10))
        self.chat_display.tag_config("time", foreground="#9aa0a6", font=("Segoe UI", 8))

        # Input area
        input_frame = tk.Frame(self.chat_frame, bg=COLOR_BG, padx=10)
        input_frame.pack(fill="x", pady=(0, 10))

        self.message_entry = tk.Entry(input_frame, font=("Segoe UI", 11))
        self.message_entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 8))
        self.message_entry.bind("<Return>", lambda e: self._on_send_clicked())

        self.send_button = tk.Button(
            input_frame, text="Send", font=("Segoe UI", 10, "bold"), bg=COLOR_OWN, fg="white",
            activebackground="#1558b0", activeforeground="white", relief="flat", padx=16,
            command=self._on_send_clicked,
        )
        self.send_button.pack(side="right")

        self.char_count_var = tk.StringVar(value="")
        tk.Label(self.chat_frame, textvariable=self.char_count_var, bg=COLOR_BG, fg="#9aa0a6",
                 font=("Segoe UI", 8)).pack(anchor="e", padx=15, pady=(0, 5))
        self.message_entry.bind("<KeyRelease>", self._update_char_count)

    def _show_chat_screen(self) -> None:
        self.login_frame.pack_forget()
        self.chat_frame.pack(fill="both", expand=True)
        self.root.title(f"{APP_NAME} - {self.client.username}")
        self.status_var.set(f"Connected as {self.client.username}")
        self.status_label.config(fg=COLOR_STATUS_OK)
        self.message_entry.focus_set()

    def _update_char_count(self, event=None) -> None:
        length = len(self.message_entry.get())
        self.char_count_var.set(f"{length}/{MAX_MESSAGE_LENGTH}")

    # ------------------------------------------------------------------
    # Sending messages
    # ------------------------------------------------------------------
    def _on_send_clicked(self) -> None:
        if not self.client.connected:
            self._append_system("You are disconnected. Cannot send messages.", is_error=True)
            return
        text = self.message_entry.get().strip()
        if not text:
            return
        error = self.client.send_chat_message(text)
        if error:
            self._append_system(error, is_error=True)
            return
        self.message_entry.delete(0, "end")
        self._update_char_count()
        self._append_chat_message(self.client.username, text, own=True)

    # ------------------------------------------------------------------
    # Incoming message handling (main-thread queue polling)
    # ------------------------------------------------------------------
    def _poll_incoming_queue(self) -> None:
        try:
            while True:
                msg = self.incoming_queue.get_nowait()
                self._handle_incoming_message(msg)
        except queue.Empty:
            pass
        finally:
            self.root.after(POLL_INTERVAL_MS, self._poll_incoming_queue)

    def _handle_incoming_message(self, msg: dict) -> None:
        msg_type = msg.get("type")
        text = msg.get("message", "")
        username = msg.get("username", "")

        if msg_type == "message":
            if username == self.client.username:
                return  # we already echoed our own message locally
            self._append_chat_message(username, text, own=False)
        elif msg_type == "system":
            self._append_system(text, is_error=False)
            if "lost" in text.lower():
                self._set_disconnected()
        elif msg_type == "error":
            self._append_system(text, is_error=True)
        # "connect"/"disconnect" types are not sent to clients by the server.

    def _set_disconnected(self) -> None:
        self.status_var.set("Disconnected")
        self.status_label.config(fg=COLOR_STATUS_BAD)
        self.send_button.config(state="disabled")
        self.message_entry.config(state="disabled")

    # ------------------------------------------------------------------
    # Chat display helpers
    # ------------------------------------------------------------------
    def _append_chat_message(self, username: str, text: str, own: bool) -> None:
        self.chat_display.config(state="normal")
        time_str = datetime.now().strftime("%H:%M")
        tag = "own" if own else "other"
        prefix = "You" if own else username
        self.chat_display.insert("end", f"{prefix}", tag)
        self.chat_display.insert("end", f"  {time_str}\n", "time")
        self.chat_display.insert("end", f"{text}\n\n", "body")
        self.chat_display.config(state="disabled")
        self.chat_display.see("end")

    def _append_system(self, text: str, is_error: bool) -> None:
        self.chat_display.config(state="normal")
        tag = "error" if is_error else "system"
        prefix = "[Error]" if is_error else "[System]"
        self.chat_display.insert("end", f"{prefix} {text}\n", tag)
        self.chat_display.config(state="disabled")
        self.chat_display.see("end")

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    def _on_close(self) -> None:
        if self.client.connected:
            self.client.disconnect()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    ChatGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
