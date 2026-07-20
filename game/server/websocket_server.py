"""
WebSocket server for Kung-Fu Chess multiplayer.

Accepts client connections, authenticates via UserService,
and delegates gameplay to a GameSession.
"""

import asyncio
import logging

import websockets

from game.server.auth.user_service import UserService
from game.server.game_session import GameSession
from game.server.protocol import (
    decode_message,
    make_error,
    validate_login_request,
)

logger = logging.getLogger(__name__)

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8765


class GameWebSocketServer:
    """
    Async WebSocket server. Authenticates clients via UserService,
    then routes gameplay messages through GameSession.
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 session: GameSession | None = None,
                 user_service: UserService | None = None):
        self.host = host
        self.port = port
        self.session = session or GameSession()
        self.user_service = user_service
        self._server = None

    async def start(self) -> None:
        """Start the server and the game tick loop."""
        self._server = await websockets.serve(
            self._handle_client, self.host, self.port
        )
        await self.session.start_tick_loop()
        logger.info(f"Server started on ws://{self.host}:{self.port}")

    async def stop(self) -> None:
        """Shut down the server and tick loop cleanly."""
        await self.session.stop_tick_loop()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("Server stopped")

    async def _handle_client(self, websocket) -> None:
        """Handle a single client connection lifecycle."""
        remote = websocket.remote_address
        logger.info(f"Client connected: {remote}")

        # Register connection. No color assigned yet — client must authenticate.
        self.session.add_client(websocket)

        try:
            async for message in websocket:
                response = await self._route_message(message, websocket)
                if response is not None:
                    if isinstance(response, list):
                        for msg in response:
                            await websocket.send(msg)
                    else:
                        await websocket.send(response)
                # Drain any queued broadcasts from engine events or accepted moves.
                await self.session.drain_outbox()
        except websockets.ConnectionClosed:
            logger.info(f"Client disconnected: {remote}")
        except Exception as e:
            logger.error(f"Error handling client {remote}: {e}")
        finally:
            self.session.remove_client(websocket)

    async def _route_message(self, raw: str, sender) -> str | list[str] | None:
        """
        Route a message: handle login_request at this layer (authentication),
        delegate everything else to GameSession.
        """
        msg = decode_message(raw)

        if msg is not None and msg.get("type") == "login_request":
            return self._handle_login_request(msg.get("payload", {}), sender)

        # All non-login messages go to GameSession
        return await self.session.handle_message(raw, sender=sender)

    def _handle_login_request(self, payload: dict, sender) -> str | list[str]:
        """
        Authenticate via UserService, then delegate player assignment to GameSession.

        GameSession never sees passwords — only the authenticated username.
        """
        # Validate message shape
        error = validate_login_request(payload)
        if error:
            return make_error(error, "invalid_login_request")

        action = payload["action"]
        username = payload["username"].strip()
        password = payload["password"]

        # If no UserService is configured, reject all logins
        if self.user_service is None:
            return make_error("authentication not available", "server_error")

        # Perform authentication or registration
        if action == "register":
            result = self.user_service.register(username, password)
        else:  # action == "login"
            result = self.user_service.authenticate(username, password)

        if not result.success:
            return make_error(
                result.error or "authentication failed",
                result.error or "invalid_credentials",
            )

        # Authentication succeeded — delegate to GameSession for player assignment
        # Use the canonical username from the database record
        canonical_username = result.user.username if result.user else username
        rating = result.user.rating if result.user else 1200
        messages = self.session.login_client(sender, canonical_username, rating=rating)
        if len(messages) == 1:
            return messages[0]
        return messages

    @property
    def client_count(self) -> int:
        return self.session.client_count


async def run_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                     user_service: UserService | None = None) -> None:
    """Run the server until interrupted."""
    server = GameWebSocketServer(
        host=host, port=port, user_service=user_service
    )
    await server.start()

    try:
        await asyncio.Future()
    except asyncio.CancelledError:
        pass
    finally:
        await server.stop()
