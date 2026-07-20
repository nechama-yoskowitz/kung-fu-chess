"""Kung-Fu Chess — application entry point.

Usage:
    python run_game.py              → local mode (offline)
    python run_game.py --server ws://localhost:8765  → network mode
"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="Kung-Fu Chess")
    parser.add_argument(
        "--server",
        type=str,
        default=None,
        help="WebSocket server URI (e.g. ws://localhost:8765). Omit for local mode.",
    )
    args = parser.parse_args()

    if args.server:
        # Network mode
        if not args.server.startswith("ws://") and not args.server.startswith("wss://"):
            print(f"Error: Invalid server URI: {args.server}")
            print("Expected format: ws://host:port")
            sys.exit(1)

        # Prompt for username
        while True:
            username = input("Enter your username: ")
            if username.strip():
                break
            print("Username cannot be empty. Please try again.")

        from game.client.network_game_application import NetworkGameApplication
        app = NetworkGameApplication(server_uri=args.server, username=username.strip())
        app.run()
    else:
        # Local mode (unchanged)
        from game.application.game_application import GameApplication
        app = GameApplication()
        app.run()


if __name__ == "__main__":
    main()
