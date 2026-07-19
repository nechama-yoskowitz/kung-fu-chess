"""
Minimal WebSocket server for Kung-Fu Chess multiplayer.

Accepts client connections, processes messages via the protocol module,
and responds. Independent from game engine and graphics.
"""

import asyncio
import logging

import websockets

from game.server.protocol import handle_message

logger = logging.getLogger(__name__)

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8765


class GameWebSocketServer:
    """
    Async WebSocket server that accepts multiple clients and handles
    messages using the protocol module.
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self._server = None
        self._clients: set = set()

    async def start(self) -> None:
        """Start the server and listen for connections."""
        self._server = await websockets.serve(
            self._handle_client, self.host, self.port
        )
        logger.info(f"Server started on ws://{self.host}:{self.port}")

    async def stop(self) -> None:
        """Shut down the server cleanly."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("Server stopped")

    async def _handle_client(self, websocket) -> None:
        """Handle a single client connection lifecycle."""
        self._clients.add(websocket)
        remote = websocket.remote_address
        logger.info(f"Client connected: {remote}")

        try:
            async for message in websocket:
                response = handle_message(message)
                await websocket.send(response)
        except websockets.ConnectionClosed:
            logger.info(f"Client disconnected: {remote}")
        except Exception as e:
            logger.error(f"Error handling client {remote}: {e}")
        finally:
            self._clients.discard(websocket)

    @property
    def client_count(self) -> int:
        return len(self._clients)


async def run_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    """Run the server until interrupted."""
    server = GameWebSocketServer(host=host, port=port)
    await server.start()

    try:
        await asyncio.Future()  # Run forever
    except asyncio.CancelledError:
        pass
    finally:
        await server.stop()
