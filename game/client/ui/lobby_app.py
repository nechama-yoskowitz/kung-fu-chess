"""
Tkinter-based graphical lobby for Kung-Fu Chess.

Screens:
- Authentication (login/register)
- Home (Play, Room, Exit)
- Room dialog (Create/Join/Cancel)

This is purely a presentation layer. All networking goes through NetworkClient.
"""

import tkinter as tk
from tkinter import messagebox
import time
import threading

from game.client.ui.network_client import NetworkClient
from game.model.constants import DEFAULT_RATING


class LobbyApp:
    """
    Main lobby application. Manages screen transitions and networking state.

    After a game session is ready, returns control so the graphical chess
    game can be launched.
    """

    def __init__(self, server_uri: str):
        self._server_uri = server_uri
        self._client = NetworkClient(server_uri)
        self._game_ready = False
        self._should_exit = False
        self._root: tk.Tk | None = None

    @property
    def game_ready(self) -> bool:
        return self._game_ready

    @property
    def client(self) -> NetworkClient:
        return self._client

    def run(self) -> bool:
        """
        Run the lobby UI. Returns True if a game is ready to start.

        After this returns True, use self.client to access transport/state
        for the graphical game.
        """
        self._client.connect()

        self._root = tk.Tk()
        self._root.title("Kung-Fu Chess")
        self._root.geometry("400x300")
        self._root.resizable(False, False)

        self._show_auth_screen()
        self._root.mainloop()

        return self._game_ready

    def _clear(self):
        """Remove all widgets from the window."""
        for widget in self._root.winfo_children():
            widget.destroy()

    # ─── Auth Screen ──────────────────────────────────────────────────────

    def _show_auth_screen(self):
        self._clear()
        self._root.title("Kung-Fu Chess - Login")

        frame = tk.Frame(self._root, padx=20, pady=20)
        frame.pack(expand=True)

        tk.Label(frame, text="Kung-Fu Chess", font=("Arial", 16, "bold")).pack(pady=(0, 15))

        tk.Label(frame, text="Username:").pack(anchor="w")
        self._username_entry = tk.Entry(frame, width=30)
        self._username_entry.pack(pady=(0, 5))

        tk.Label(frame, text="Password:").pack(anchor="w")
        self._password_entry = tk.Entry(frame, width=30, show="*")
        self._password_entry.pack(pady=(0, 10))

        btn_frame = tk.Frame(frame)
        btn_frame.pack()
        tk.Button(btn_frame, text="Login", width=10,
                  command=lambda: self._do_auth("login")).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Register", width=10,
                  command=lambda: self._do_auth("register")).pack(side="left", padx=5)

        self._auth_status = tk.Label(frame, text="", fg="red")
        self._auth_status.pack(pady=(10, 0))

    def _do_auth(self, action: str):
        username = self._username_entry.get().strip()
        password = self._password_entry.get()

        if not username:
            self._auth_status.config(text="Username cannot be empty.")
            return
        if not password:
            self._auth_status.config(text="Password cannot be empty.")
            return

        self._auth_status.config(text="Connecting...", fg="gray")
        self._client.send_login(username, password, action)

        # Poll for response
        self._root.after(100, self._check_auth_response)

    def _check_auth_response(self):
        if self._game_ready:
            return

        messages = self._client.poll_messages()
        is_reconnect = False
        found_login = False
        found_game_state = False
        game_state_payload = None

        for msg in messages:
            msg_type = msg.get("type", "")
            payload = msg.get("payload", {})

            if msg_type == "login_success" and not found_login:
                self._client.state.apply_login_success(
                    payload.get("color") or None,
                    payload.get("username", ""),
                    payload.get("rating", DEFAULT_RATING),
                )
                is_reconnect = payload.get("reconnected", False)
                found_login = True
                continue  # Keep scanning for game_state in same batch
            elif msg_type == "error":
                self._auth_status.config(
                    text=payload.get("message", "Authentication failed."), fg="red"
                )
                return
            elif msg_type == "game_state":
                game_state_payload = payload
                found_game_state = True
                break  # Found everything we need

        if found_login:
            if is_reconnect:
                if found_game_state:
                    # Both arrived in same batch — launch immediately
                    self._apply_game_state(game_state_payload)
                    self._start_game()
                else:
                    # game_state will arrive later — wait for it
                    self._handle_reconnect()
            else:
                self._show_home_screen()
            return

        # Still waiting for login response
        self._root.after(100, self._check_auth_response)

    def _handle_reconnect(self):
        """After reconnect login_success, wait for game_state."""
        self._clear()
        tk.Label(self._root, text="Reconnecting to active game...",
                 font=("Arial", 12)).pack(expand=True)
        self._reconnect_deadline = time.monotonic() + 5.0
        self._root.after(50, self._check_reconnect_game_state)

    def _check_reconnect_game_state(self):
        if self._game_ready:
            return

        messages = self._client.poll_messages()
        for msg in messages:
            if msg.get("type") == "game_state":
                self._apply_game_state(msg.get("payload", {}))
                self._start_game()
                return

        if time.monotonic() > self._reconnect_deadline:
            self._auth_status = tk.Label(self._root, text="Reconnect failed.", fg="red")
            self._auth_status.pack()
            self._root.after(2000, self._show_home_screen)
            return

        self._root.after(50, self._check_reconnect_game_state)

    # ─── Home Screen ──────────────────────────────────────────────────────

    def _show_home_screen(self):
        self._clear()
        self._root.title("Kung-Fu Chess - Home")

        frame = tk.Frame(self._root, padx=20, pady=20)
        frame.pack(expand=True)

        state = self._client.state
        info = f"{state.player_username} | Rating: {state.player_rating}"
        tk.Label(frame, text=info, font=("Arial", 12)).pack(pady=(0, 20))

        tk.Button(frame, text="Play (Matchmaking)", width=20,
                  command=self._do_matchmaking).pack(pady=5)
        tk.Button(frame, text="Room", width=20,
                  command=self._show_room_dialog).pack(pady=5)
        tk.Button(frame, text="Exit", width=20,
                  command=self._do_exit).pack(pady=5)

        self._home_status = tk.Label(frame, text="", fg="gray")
        self._home_status.pack(pady=(10, 0))

    # ─── Matchmaking ──────────────────────────────────────────────────────

    def _do_matchmaking(self):
        self._client.send_play_request()
        self._home_status.config(text="Searching for opponent...")
        self._mm_deadline = time.monotonic() + 65.0
        self._root.after(200, self._check_matchmaking)

    def _check_matchmaking(self):
        if self._game_ready:
            return

        messages = self._client.poll_messages()
        match_found = False
        game_state_payload = None

        for msg in messages:
            msg_type = msg.get("type", "")
            payload = msg.get("payload", {})

            if msg_type == "match_found":
                self._client.state.apply_match_found(payload)
                match_found = True
                continue  # Keep scanning for game_state in same batch
            elif msg_type == "matchmaking_timeout":
                self._home_status.config(text="No opponent found. Try again.")
                return
            elif msg_type == "game_state":
                game_state_payload = payload
                break

        if game_state_payload:
            self._apply_game_state(game_state_payload)
            if match_found:
                self._home_status.config(text="Match found! Starting game...")
            self._start_game()
            return

        if match_found:
            self._home_status.config(text="Match found! Starting game...")
            self._root.after(100, self._wait_for_game_state)
            return

        if time.monotonic() > self._mm_deadline:
            self._home_status.config(text="Matchmaking timed out.")
            return

        self._root.after(200, self._check_matchmaking)

    def _wait_for_game_state(self):
        if self._game_ready:
            return

        messages = self._client.poll_messages()
        for msg in messages:
            if msg.get("type") == "game_state":
                self._apply_game_state(msg.get("payload", {}))
                self._start_game()
                return
        self._root.after(100, self._wait_for_game_state)

    # ─── Room Dialog ──────────────────────────────────────────────────────

    def _show_room_dialog(self):
        self._clear()
        self._root.title("Kung-Fu Chess - Room")

        frame = tk.Frame(self._root, padx=20, pady=20)
        frame.pack(expand=True)

        tk.Label(frame, text="Room", font=("Arial", 14, "bold")).pack(pady=(0, 15))

        tk.Label(frame, text="Room ID:").pack(anchor="w")
        self._room_id_entry = tk.Entry(frame, width=30)
        self._room_id_entry.pack(pady=(0, 10))

        btn_frame = tk.Frame(frame)
        btn_frame.pack()
        tk.Button(btn_frame, text="Create", width=10,
                  command=self._do_create_room).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Join", width=10,
                  command=self._do_join_room).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Cancel", width=10,
                  command=self._show_home_screen).pack(side="left", padx=5)

        self._room_status = tk.Label(frame, text="", fg="gray")
        self._room_status.pack(pady=(10, 0))

    def _do_create_room(self):
        self._client.send_create_room()
        self._room_status.config(text="Creating room...")
        self._root.after(100, self._check_room_created)

    def _check_room_created(self):
        messages = self._client.poll_messages()
        for msg in messages:
            msg_type = msg.get("type", "")
            payload = msg.get("payload", {})

            if msg_type == "room_created":
                room_id = payload.get("room_id", "")
                self._client.state.apply_room_created(room_id)
                self._show_waiting_for_opponent(room_id)
                return
            elif msg_type == "error":
                self._room_status.config(
                    text=payload.get("message", "Failed to create room."), fg="red"
                )
                return

        self._root.after(100, self._check_room_created)

    def _show_waiting_for_opponent(self, room_id: str):
        self._clear()
        frame = tk.Frame(self._root, padx=20, pady=20)
        frame.pack(expand=True)

        tk.Label(frame, text=f"Room ID: {room_id}", font=("Arial", 14, "bold")).pack(pady=10)
        tk.Label(frame, text="Waiting for opponent to join...").pack(pady=5)
        tk.Button(frame, text="Cancel / Leave", width=15,
                  command=self._do_leave_room).pack(pady=10)

        self._wait_room_deadline = time.monotonic() + 300.0
        self._root.after(200, self._check_room_game_state)

    def _check_room_game_state(self):
        if self._game_ready:
            return

        messages = self._client.poll_messages()
        for msg in messages:
            if msg.get("type") == "game_state":
                self._apply_game_state(msg.get("payload", {}))
                self._client.state.player_color = "w"
                self._start_game()
                return

        if time.monotonic() > self._wait_room_deadline:
            self._do_leave_room()
            return

        self._root.after(200, self._check_room_game_state)

    def _do_leave_room(self):
        self._client.send_leave_room()
        self._show_home_screen()

    def _do_join_room(self):
        room_id = self._room_id_entry.get().strip()
        if not room_id:
            self._room_status.config(text="Room ID cannot be empty.", fg="red")
            return

        self._client.send_join_room(room_id)
        self._room_status.config(text="Joining...")
        self._root.after(100, lambda: self._check_room_joined(room_id))

    def _check_room_joined(self, room_id: str):
        if self._game_ready:
            return

        messages = self._client.poll_messages()
        joined = False
        for msg in messages:
            msg_type = msg.get("type", "")
            payload = msg.get("payload", {})

            if msg_type == "room_joined":
                role = payload.get("role", "player")
                color = payload.get("color")
                self._client.state.apply_room_joined(room_id, role, color)
                joined = True
                continue  # Don't break — keep scanning for game_state
            elif msg_type == "game_state":
                self._apply_game_state(payload)
                self._start_game()
                return
            elif msg_type == "error":
                self._room_status.config(
                    text=payload.get("message", "Failed to join room."), fg="red"
                )
                return

        if joined:
            # room_joined received but game_state not yet — wait for it
            self._root.after(100, self._wait_for_game_state)
            return

        self._root.after(100, lambda: self._check_room_joined(room_id))

    # ─── Helpers ──────────────────────────────────────────────────────────

    def _apply_game_state(self, payload: dict):
        self._client.state.apply_game_state(
            payload.get("board", []),
            payload.get("clock", 0.0),
            payload.get("white_score", 0),
            payload.get("black_score", 0),
            payload.get("game_over", False),
        )

    def _start_game(self):
        """Close the lobby and signal that the game is ready."""
        if self._game_ready:
            return  # Guard against double-launch
        self._game_ready = True
        self._root.destroy()

    def _do_exit(self):
        self._should_exit = True
        self._client.disconnect()
        self._root.destroy()
