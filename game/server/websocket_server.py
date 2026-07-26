"""
WebSocket transport layer for Kung-Fu Chess multiplayer.

Responsible only for:
- Starting/stopping the server
- Accepting and closing WebSocket connections
- Receiving raw frames and delegating to the application router
- Sending encoded outbound messages
- Running periodic background tasks (matchmaking, reconnect polls)

All application logic (authentication, matchmaking decisions, session routing,
room management, reconnect orchestration) is handled by ClientSessionRouter.
"""

import asyncio
import logging

import websockets

from game.server.auth.user_service import UserService
from game.server.connection_router import ClientSessionRouter
from game.server.game_session import GameSession
from game.server.game_session_manager import GameSessionManager
from game.server.matchmaking.matchmaking_service import MatchmakingService
from game.server.rating.rating_service import RatingService
from game.server.reconnect_manager import ReconnectManager
from game.server.room_manager import RoomManager

logger = logging.getLogger(__name__)

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8765

MATCHMAKING_POLL_INTERVAL = 0.5  # seconds


class GameWebSocketServer:
    """
    Async WebSocket transport. Delegates all application decisions to
    ClientSessionRouter.
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 session: GameSession | None = None,
                 user_service: UserService | None = None,
                 rating_service: RatingService | None = None,
                 matchmaking: MatchmakingService | None = None,
                 session_manager: GameSessionManager | None = None,
                 reconnect_manager: ReconnectManager | None = None):
        self.host = host
        self.port = port
        self._server = None
        self._connected: set = set()
        self._matchmaking_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None

        # Build collaborators
        sm = session_manager or GameSessionManager()
        mm = matchmaking or MatchmakingService()
        rm = reconnect_manager or ReconnectManager()
        room_mgr = RoomManager(sm)

        # Application router owns all business logic
        self.router = ClientSessionRouter(
            user_service=user_service,
            rating_service=rating_service,
            matchmaking=mm,
            session_manager=sm,
            reconnect_manager=rm,
            room_manager=room_mgr,
            legacy_session=session,
        )

        # Expose collaborators for test access (read-only inspection)
        self.session_manager = sm
        self.matchmaking = mm
        self.reconnect_manager = rm
        self.room_manager = room_mgr
        self.user_service = user_service
        self.rating_service = rating_service

        # Backward compat: tests reference self.session
        self.session = session

    async def start(self) -> None:
        """Start the WebSocket server and background loops."""
        self._server = await websockets.serve(
            self._handle_client, self.host, self.port
        )
        for session in self.session_manager.iter_sessions():
            await session.start_tick_loop()
        self._matchmaking_task = asyncio.create_task(self._matchmaking_loop())
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())
        logger.info(f"Server started on ws://{self.host}:{self.port}")

    async def stop(self) -> None:
        """Shut down server and background tasks."""
        if self._matchmaking_task:
            self._matchmaking_task.cancel()
            try:
                await self._matchmaking_task
            except asyncio.CancelledError:
                pass
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        for session in list(self.session_manager.iter_sessions()):
            await session.stop_tick_loop()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("Server stopped")

    # ─── Transport: connection lifecycle ──────────────────────────────────

    async def _handle_client(self, websocket) -> None:
        """Handle a single client connection lifecycle."""
        remote = websocket.remote_address
        logger.info(f"Client connected: {remote}")
        self._connected.add(websocket)

        try:
            async for message in websocket:
                response = await self.router.route_message(message, websocket)
                await self._send_response(websocket, response)
                # Drain session outbox (broadcasts queued by game logic)
                session = self.session_manager.get_session_for_client(websocket)
                if session:
                    await session.drain_outbox()
        except websockets.ConnectionClosed:
            logger.info(f"Client disconnected: {remote}")
        except Exception as e:
            logger.error(f"Error handling client {remote}: {e}")
        finally:
            self._connected.discard(websocket)
            self.router.on_disconnect(websocket)

    # ─── Transport: send helpers ──────────────────────────────────────────

    async def _send_response(self, websocket, response) -> None:
        """Send a response (str, list[str], or None) to the client."""
        if response is None:
            return
        if isinstance(response, list):
            for msg in response:
                await websocket.send(msg)
        else:
            await websocket.send(response)

    async def _send_to_client(self, websocket, message: str) -> None:
        """Send a single message to a specific client (callback for router)."""
        await websocket.send(message)

    # ─── Transport: background loops ──────────────────────────────────────

    async def _matchmaking_loop(self) -> None:
        """Periodically poll matchmaking."""
        while True:
            await asyncio.sleep(MATCHMAKING_POLL_INTERVAL)
            await self.router.process_matchmaking(self._send_to_client)

    async def _reconnect_loop(self) -> None:
        """Periodically check for expired reconnect deadlines."""
        while True:
            await asyncio.sleep(1.0)
            await self.router.process_reconnect_expirations()

    # ─── Transport: public inspection ─────────────────────────────────────

    @property
    def client_count(self) -> int:
        return len(self._connected)

    # ─── Backward compatibility for tests that call _route_message ────────

    async def _route_message(self, raw: str, sender) -> str | list[str] | None:
        """Compatibility shim — delegates to router."""
        return await self.router.route_message(raw, sender)

    def _cleanup_client(self, websocket) -> None:
        """Compatibility shim — delegates to router."""
        self._connected.discard(websocket)
        self.router.on_disconnect(websocket)

    async def _process_matchmaking(self) -> None:
        """Compatibility shim — delegates to router."""
        await self.router.process_matchmaking(self._send_to_client)

    async def _process_reconnect_expirations(self) -> None:
        """Compatibility shim — delegates to router."""
        await self.router.process_reconnect_expirations()

    def _handle_login_request(self, payload: dict, sender) -> str | list[str]:
        """Compatibility shim — delegates to router."""
        return self.router._handle_login_request(payload, sender)

    @property
    def _authenticated(self):
        """Compatibility shim — delegates to router."""
        return self.router._authenticated


async def run_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                     user_service: UserService | None = None,
                     rating_service: RatingService | None = None) -> None:
    """Run the server until interrupted."""
    server = GameWebSocketServer(
        host=host, port=port,
        user_service=user_service,
        rating_service=rating_service,
    )
    await server.start()

    try:
        await asyncio.Future()
    except asyncio.CancelledError:
        pass
    finally:
        await server.stop()
