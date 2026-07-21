"""
Room management for Kung-Fu Chess server.

Responsibilities:
- Create rooms with unique IDs
- Track room membership: players (White/Black) and viewers
- Join rooms by ID (player or viewer)
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
    players: list = field(default_factory=list)  # websockets (max 2)
    viewers: list = field(default_factory=list)  # websockets (unlimited)

    @property
    def is_full(self) -> bool:
        """True if both player slots are taken."""
        return len(self.players) >= MAX_PLAYERS_PER_ROOM

    @property
    def member_count(self) -> int:
        return len(self.players) + len(self.viewers)

    def is_player(self, websocket) -> bool:
        return websocket in self.players

    def is_viewer(self, websocket) -> bool:
        return websocket in self.viewers

    def get_role(self, websocket) -> str | None:
        if websocket in self.players:
            return "player"
        if websocket in self.viewers:
            return "viewer"
        return None


class RoomManager:
    """
    Creates and manages named rooms backed by GameSessions.

    Each room has a unique ID. The first two joiners are players (White/Black).
    Additional joiners become viewers.
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

    def join_room(self, room_id: str, websocket, username: str, rating: int = 1200) -> tuple[str | None, str]:
        """
        Add a client to a room as player or viewer.

        Returns (error, role):
        - (None, "player") on success as player
        - (None, "viewer") on success as viewer
        - ("room_not_found", "") on failure
        """
        room = self._rooms.get(room_id)
        if room is None:
            return "room_not_found", ""

        if room.is_full:
            # Add as viewer
            room.viewers.append(websocket)
            room.session.add_viewer(websocket)
            self._session_manager.assign_client_to_session(websocket, room.session)
            return None, "viewer"
        else:
            # Add as player
            room.players.append(websocket)
            room.session.add_client(websocket)
            room.session.login_client(websocket, username, rating=rating)
            self._session_manager.assign_client_to_session(websocket, room.session)
            return None, "player"

    def remove_room(self, room_id: str) -> None:
        """Remove a room and its session."""
        room = self._rooms.pop(room_id, None)
        if room:
            self._session_manager.remove_session(room.session)

    def remove_client(self, websocket) -> None:
        """Remove a player or viewer from their room. Deletes room if empty."""
        for room_id, room in list(self._rooms.items()):
            if websocket in room.players:
                room.players.remove(websocket)
                if not room.players and not room.viewers:
                    self.remove_room(room_id)
                return
            if websocket in room.viewers:
                room.viewers.remove(websocket)
                if not room.players and not room.viewers:
                    self.remove_room(room_id)
                return

    def get_room_for_client(self, websocket) -> Room | None:
        """Find the room a client (player or viewer) belongs to."""
        for room in self._rooms.values():
            if websocket in room.players or websocket in room.viewers:
                return room
        return None

    # Keep backward compat for existing tests
    def remove_player(self, websocket) -> None:
        """Alias for remove_client."""
        self.remove_client(websocket)

    def get_room_for_player(self, websocket) -> Room | None:
        """Alias for get_room_for_client."""
        return self.get_room_for_client(websocket)

    @staticmethod
    def _generate_id() -> str:
        return uuid.uuid4().hex[:8]
