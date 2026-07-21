"""
Room management for Kung-Fu Chess server.

Responsibilities:
- Create rooms with unique IDs
- Track room metadata (creator, players, session)
- Join rooms by ID
- Remove empty/finished rooms

Does not own GameSession lifecycle — delegates to GameSessionManager.
"""

import uuid
from dataclasses import dataclass, field

from game.server.game_session import GameSession
from game.server.game_session_manager import GameSessionManager


MAX_PLAYERS_PER_ROOM = 2


@dataclass
class Room:
    """Metadata for one active room."""

    room_id: str
    session: GameSession
    players: list = field(default_factory=list)  # list of websockets

    @property
    def is_full(self) -> bool:
        return len(self.players) >= MAX_PLAYERS_PER_ROOM


class RoomManager:
    """
    Creates and manages named rooms backed by GameSessions.

    Each room has a unique ID. Players join by ID.
    The first player is White, the second is Black.
    """

    def __init__(self, session_manager: GameSessionManager):
        self._session_manager = session_manager
        self._rooms: dict[str, Room] = {}

    @property
    def room_count(self) -> int:
        return len(self._rooms)

    def create_room(self) -> Room:
        """Create a new room with a unique ID and fresh GameSession."""
        room_id = self._generate_id()
        session = self._session_manager.create_session()
        room = Room(room_id=room_id, session=session)
        self._rooms[room_id] = room
        return room

    def get_room(self, room_id: str) -> Room | None:
        """Look up a room by ID."""
        return self._rooms.get(room_id)

    def join_room(self, room_id: str, websocket, username: str, rating: int = 1200) -> str | None:
        """
        Add a player to a room.

        Returns None on success, or an error code string on failure:
        - "room_not_found"
        - "room_full"
        """
        room = self._rooms.get(room_id)
        if room is None:
            return "room_not_found"
        if room.is_full:
            return "room_full"

        room.players.append(websocket)
        room.session.add_client(websocket)
        room.session.login_client(websocket, username, rating=rating)
        self._session_manager.assign_client_to_session(websocket, room.session)
        return None

    def remove_room(self, room_id: str) -> None:
        """Remove a room and its session."""
        room = self._rooms.pop(room_id, None)
        if room:
            self._session_manager.remove_session(room.session)

    def remove_player(self, websocket) -> None:
        """Remove a player from their room. Deletes the room if empty."""
        for room_id, room in list(self._rooms.items()):
            if websocket in room.players:
                room.players.remove(websocket)
                if not room.players:
                    self.remove_room(room_id)
                return

    def get_room_for_player(self, websocket) -> Room | None:
        """Find the room a player belongs to."""
        for room in self._rooms.values():
            if websocket in room.players:
                return room
        return None

    @staticmethod
    def _generate_id() -> str:
        return uuid.uuid4().hex[:8]
