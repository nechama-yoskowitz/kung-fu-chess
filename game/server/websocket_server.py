"""
WebSocket server for Kung-Fu Chess multiplayer.

Accepts client connections and delegates gameplay to a GameSession.
"""

import asyncio
import logging

import websockets

from game.server.game_session import GameSession

logger = logging.getLogger(__name__)

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8765


class GameWebSocketServer:
    """
    Async WebSocket server. Creates a GameSession and routes
    client messages through it.
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 session: GameSession | None = None):
        self.host = host
        self.port = port
        self.session = session or GameSession()
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

        # Send initial messages (player_assigned + game_state, or game_full error).
        initial_messages = self.session.add_client(websocket)
        for msg in initial_messages:
            await websocket.send(msg)

        # If the client was rejected (game_full), close immediately.
        if websocket not in self.session._clients:
            await websocket.close()
            return

        try:
            async for message in websocket:
                response = await self.session.handle_message(message, sender=websocket)
                if response is not None:
                    await websocket.send(response)
                # Drain any queued broadcasts from engine events or accepted moves.
                await self.session.drain_outbox()
        except websockets.ConnectionClosed:
            logger.info(f"Client disconnected: {remote}")
        except Exception as e:
            logger.error(f"Error handling client {remote}: {e}")
        finally:
            self.session.remove_client(websocket)

    @property
    def client_count(self) -> int:
        return self.session.client_count


async def run_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    """Run the server until interrupted."""
    server = GameWebSocketServer(host=host, port=port)
    await server.start()

    try:
        await asyncio.Future()
    except asyncio.CancelledError:
        pass
    finally:
        await server.stop()
