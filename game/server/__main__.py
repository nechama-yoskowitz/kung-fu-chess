"""
Entry point: python -m game.server

Starts the WebSocket server on localhost:8765 with SQLite-backed authentication.
"""

import asyncio
import logging

from game.server.auth.user_repository import UserRepository
from game.server.auth.user_service import UserService
from game.server.rating.rating_service import RatingService
from game.server.websocket_server import run_server, DEFAULT_HOST, DEFAULT_PORT

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DB_PATH = "kungfu_chess.db"


def main():
    # Initialize persistence
    repo = UserRepository(DB_PATH)
    repo.initialize_schema()
    user_service = UserService(repo)
    rating_service = RatingService(repository=repo)

    print(f"Starting Kung-Fu Chess server on ws://{DEFAULT_HOST}:{DEFAULT_PORT}")
    print(f"Database: {DB_PATH}")
    print("Press Ctrl+C to stop.")
    try:
        asyncio.run(run_server(
            host=DEFAULT_HOST,
            port=DEFAULT_PORT,
            user_service=user_service,
            rating_service=rating_service,
        ))
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
