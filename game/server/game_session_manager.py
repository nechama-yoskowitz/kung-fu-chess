"""
Manages multiple simultaneous GameSession instances.

Responsibilities:
- Create new sessions for matched players
- Track which websocket belongs to which session
- Remove finished sessions
- Look up sessions by ID or websocket
"""

import logging

from game.server.game_session import GameSession

logger = logging.getLogger(__name__)


class GameSessionManager:
    """
    Registry for active GameSession objects.

    Each session has a unique string ID derived from its engine identity.
    Clients are mapped to their active session for message routing.
    """

    def __init__(self):
        # session_id → GameSession
        self._sessions: dict[str, GameSession] = {}
        # websocket → session_id
        self._client_sessions: dict[object, str] = {}

    @property
    def active_session_count(self) -> int:
        return len(self._sessions)

    def create_session(self) -> GameSession:
        """Create a new GameSession and register it."""
        session = GameSession()
        session_id = f"game-{id(session.engine)}"
        self._sessions[session_id] = session
        return session

    def get_session_id(self, session: GameSession) -> str | None:
        """Return the session ID for a given session object."""
        for sid, s in self._sessions.items():
            if s is session:
                return sid
        return None

    def get_session_by_id(self, session_id: str) -> GameSession | None:
        """Look up a session by its ID."""
        return self._sessions.get(session_id)

    def get_session_for_client(self, websocket) -> GameSession | None:
        """Return the session a client is currently in, or None."""
        session_id = self._client_sessions.get(websocket)
        if session_id is None:
            return None
        return self._sessions.get(session_id)

    def assign_client_to_session(self, websocket, session: GameSession) -> None:
        """Map a websocket to a session."""
        session_id = self.get_session_id(session)
        if session_id is None:
            raise ValueError("Session not registered in manager")
        self._client_sessions[websocket] = session_id

    def remove_client(self, websocket) -> None:
        """Remove a client's session mapping."""
        self._client_sessions.pop(websocket, None)

    def remove_session(self, session: GameSession) -> None:
        """Remove a finished session and all its client mappings."""
        session_id = self.get_session_id(session)
        if session_id is None:
            return

        # Remove all client mappings for this session
        to_remove = [
            ws for ws, sid in self._client_sessions.items()
            if sid == session_id
        ]
        for ws in to_remove:
            del self._client_sessions[ws]

        del self._sessions[session_id]
        logger.info(f"Session {session_id} removed")

    def is_client_in_session(self, websocket) -> bool:
        """Check if a client is currently assigned to any session."""
        return websocket in self._client_sessions
