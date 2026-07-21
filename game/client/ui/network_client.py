"""
Thin network facade for the UI layer.

Wraps NetworkTransport + protocol message construction so UI callbacks
never touch WebSockets, queues, or raw protocol strings directly.
"""

import queue
import time
from typing import Callable

from game.client.client_game_state import ClientGameState
from game.client.network_transport import NetworkTransport
from game.server.protocol import (
    make_cancel_matchmaking,
    make_create_room,
    make_join_room,
    make_leave_room,
    make_login_request,
    make_play_request,
)


class NetworkClient:
    """
    High-level network client for the UI layer.

    Encapsulates transport, queues, and protocol. UI code calls
    simple methods like login(), create_room(), etc.
    """

    def __init__(self, server_uri: str):
        self.state = ClientGameState()
        self._outgoing: queue.Queue = queue.Queue()
        self._incoming: queue.Queue = queue.Queue()
        self._transport = NetworkTransport(server_uri, self._outgoing, self._incoming)

    @property
    def transport(self):
        return self._transport

    @property
    def outgoing(self):
        return self._outgoing

    @property
    def incoming(self):
        return self._incoming

    def connect(self) -> None:
        """Start the background transport."""
        self._transport.start()

    def disconnect(self) -> None:
        """Stop the transport."""
        self._transport.stop(timeout=2.0)

    def send_login(self, username: str, password: str, action: str = "login") -> None:
        """Send a login or register request."""
        self._outgoing.put_nowait(make_login_request(username, password, action))

    def send_play_request(self) -> None:
        """Enter matchmaking queue."""
        self._outgoing.put_nowait(make_play_request())

    def send_cancel_matchmaking(self) -> None:
        """Cancel matchmaking."""
        self._outgoing.put_nowait(make_cancel_matchmaking())

    def send_create_room(self) -> None:
        """Create a new room."""
        self._outgoing.put_nowait(make_create_room())

    def send_join_room(self, room_id: str) -> None:
        """Join an existing room."""
        self._outgoing.put_nowait(make_join_room(room_id))

    def send_leave_room(self) -> None:
        """Leave the current room."""
        self._outgoing.put_nowait(make_leave_room())

    def poll_messages(self) -> list[dict]:
        """Drain all pending incoming messages (non-blocking)."""
        return self._transport.drain_incoming()

    def wait_for_message(self, msg_type: str, timeout: float = 5.0) -> dict | None:
        """
        Block until a specific message type arrives or timeout.

        Returns the message dict or None on timeout.
        Other messages received during the wait are discarded.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            messages = self.poll_messages()
            for msg in messages:
                if msg.get("type") == msg_type:
                    return msg
            time.sleep(0.05)
        return None
