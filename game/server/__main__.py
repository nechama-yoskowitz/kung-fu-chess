"""
Entry point: python -m game.server

Starts the WebSocket server on localhost:8765.
"""

import asyncio
import logging

from game.server.websocket_server import run_server, DEFAULT_HOST, DEFAULT_PORT

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main():
    print(f"Starting Kung-Fu Chess server on ws://{DEFAULT_HOST}:{DEFAULT_PORT}")
    print("Press Ctrl+C to stop.")
    try:
        asyncio.run(run_server(host=DEFAULT_HOST, port=DEFAULT_PORT))
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
