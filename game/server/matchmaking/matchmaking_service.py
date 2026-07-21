"""
ELO-based matchmaking queue.

Responsibilities:
- Accept play requests from authenticated players
- Match players within ±100 ELO (oldest compatible first)
- Enforce 60-second timeout
- Handle cancellation and disconnect

Does not know about WebSockets, protocol serialization, or GameSession internals.
"""

import time
from dataclasses import dataclass


RATING_THRESHOLD = 100
TIMEOUT_SECONDS = 60.0


@dataclass
class QueueEntry:
    """A player waiting in the matchmaking queue."""

    websocket: object
    username: str
    rating: int
    enqueue_time: float


@dataclass(frozen=True)
class MatchResult:
    """The result of a successful match between two players."""

    player1: QueueEntry
    player2: QueueEntry


class MatchmakingService:
    """
    ELO-based matchmaking queue.

    Players are matched when their rating difference is at most RATING_THRESHOLD.
    Oldest compatible opponent is preferred.
    """

    def __init__(self, rating_threshold: int = RATING_THRESHOLD,
                 timeout_seconds: float = TIMEOUT_SECONDS):
        self._queue: list[QueueEntry] = []
        self._rating_threshold = rating_threshold
        self._timeout_seconds = timeout_seconds

    @property
    def queue_size(self) -> int:
        return len(self._queue)

    def enqueue(self, websocket, username: str, rating: int) -> bool:
        """
        Add a player to the matchmaking queue.

        Returns True if added, False if already in queue.
        """
        for entry in self._queue:
            if entry.websocket is websocket or entry.username == username:
                return False
        self._queue.append(QueueEntry(
            websocket=websocket,
            username=username,
            rating=rating,
            enqueue_time=time.monotonic(),
        ))
        return True

    def cancel(self, websocket) -> bool:
        """
        Remove a player from the queue by websocket.

        Returns True if removed, False if not found.
        """
        for i, entry in enumerate(self._queue):
            if entry.websocket is websocket:
                self._queue.pop(i)
                return True
        return False

    def is_queued(self, websocket) -> bool:
        """Check if a websocket is currently in the queue."""
        return any(e.websocket is websocket for e in self._queue)

    def try_match(self) -> MatchResult | None:
        """
        Attempt to find a compatible match from the queue.

        Iterates the queue in order and for each player, finds the oldest
        compatible opponent. Returns the first valid match found, or None.
        """
        for i, entry in enumerate(self._queue):
            for j in range(i + 1, len(self._queue)):
                other = self._queue[j]
                if abs(entry.rating - other.rating) <= self._rating_threshold:
                    # Match found — remove both
                    # Remove higher index first to avoid shifting
                    self._queue.pop(j)
                    self._queue.pop(i)
                    return MatchResult(player1=entry, player2=other)
        return None

    def get_timed_out(self) -> list[QueueEntry]:
        """
        Remove and return all entries that have exceeded the timeout.

        Returns the removed entries in queue order.
        """
        now = time.monotonic()
        timed_out = []
        remaining = []

        for entry in self._queue:
            if now - entry.enqueue_time >= self._timeout_seconds:
                timed_out.append(entry)
            else:
                remaining.append(entry)

        self._queue = remaining
        return timed_out

    def remove_by_websocket(self, websocket) -> QueueEntry | None:
        """Remove a specific websocket from the queue (e.g. on disconnect)."""
        for i, entry in enumerate(self._queue):
            if entry.websocket is websocket:
                return self._queue.pop(i)
        return None
