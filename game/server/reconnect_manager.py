"""
Manages player reconnection after disconnect.

When an active player disconnects, their slot is reserved for RECONNECT_TIMEOUT
seconds. If they reconnect (same username), they resume. If not, auto-resign.

Does not know about WebSockets, protocol, or GameEngine internals.
Uses an injectable time provider for testability.
"""

import time
from dataclasses import dataclass


RECONNECT_TIMEOUT = 20.0  # seconds


@dataclass
class PendingReconnect:
    """A reserved player slot awaiting reconnection."""

    username: str
    color: str  # "w" or "b"
    room_id: str | None
    session_id: str
    disconnect_time: float
    deadline: float


class ReconnectManager:
    """
    Tracks disconnected players and their reconnection deadlines.

    Uses time_provider() for testability (defaults to time.monotonic).
    """

    def __init__(self, timeout: float = RECONNECT_TIMEOUT,
                 time_provider=None):
        self._timeout = timeout
        self._time = time_provider or time.monotonic
        # username → PendingReconnect
        self._pending: dict[str, PendingReconnect] = {}

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def start_reconnect(self, username: str, color: str,
                        room_id: str | None, session_id: str) -> PendingReconnect:
        """
        Register a disconnected player for potential reconnection.

        Returns the PendingReconnect record.
        """
        now = self._time()
        record = PendingReconnect(
            username=username,
            color=color,
            room_id=room_id,
            session_id=session_id,
            disconnect_time=now,
            deadline=now + self._timeout,
        )
        self._pending[username] = record
        return record

    def try_reconnect(self, username: str) -> PendingReconnect | None:
        """
        Attempt to reconnect a user.

        Returns the PendingReconnect if valid and not expired, else None.
        Does NOT remove it — caller should call cancel() after successful restore.
        """
        record = self._pending.get(username)
        if record is None:
            return None
        if self._time() > record.deadline:
            # Expired — remove and return None
            del self._pending[username]
            return None
        return record

    def cancel(self, username: str) -> PendingReconnect | None:
        """Remove and return a pending reconnect (e.g. after successful reconnection)."""
        return self._pending.pop(username, None)

    def has_pending(self, username: str) -> bool:
        """Check if a user has a pending reconnect slot."""
        return username in self._pending

    def get_expired(self) -> list[PendingReconnect]:
        """Remove and return all expired records."""
        now = self._time()
        expired = []
        remaining = {}
        for username, record in self._pending.items():
            if now >= record.deadline:
                expired.append(record)
            else:
                remaining[username] = record
        self._pending = remaining
        return expired

    def get_remaining_seconds(self, username: str) -> float:
        """Return remaining seconds for a pending reconnect, or 0 if expired/not found."""
        record = self._pending.get(username)
        if record is None:
            return 0.0
        remaining = record.deadline - self._time()
        return max(0.0, remaining)

    def get_all_pending(self) -> list[PendingReconnect]:
        """Return all currently pending reconnects (for countdown broadcasts)."""
        return list(self._pending.values())
