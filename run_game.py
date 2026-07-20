"""Kung-Fu Chess — application entry point.

Usage:
    python run_game.py              → local mode (offline)
    python run_game.py --server ws://localhost:8765  → network mode
"""

import argparse
import getpass
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

        # Prompt for register/login
        while True:
            print("1. Register")
            print("2. Login")
            choice = input("Choose (1/2): ").strip()
            if choice == "1":
                action = "register"
                break
            elif choice == "2":
                action = "login"
                break
            print("Please enter 1 or 2.")

        # Prompt for username
        while True:
            username = input("Username: ")
            if username.strip():
                break
            print("Username cannot be empty.")

        # Prompt for password (not echoed)
        while True:
            password = getpass.getpass("Password: ")
            if password:
                break
            print("Password cannot be empty.")

        from game.client.network_game_application import NetworkGameApplication
        app = NetworkGameApplication(
            server_uri=args.server,
            username=username.strip(),
            password=password,
            action=action,
        )
        # Clear password from local scope
        password = None  # noqa: F841
        app.run()
    else:
        # Local mode (unchanged)
        from game.application.game_application import GameApplication
        app = GameApplication()
        app.run()


if __name__ == "__main__":
    main()
