"""Kung-Fu Chess — application entry point.

Usage:
    python run_game.py              → local mode (offline)
    python run_game.py --server ws://localhost:8765  → network mode
"""

import argparse
import getpass
import queue
import sys
import time

from game.server.protocol import (
    decode_message,
    make_cancel_matchmaking,
    make_create_room,
    make_join_room,
    make_login_request,
    make_play_request,
)


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
        _run_network_mode(args.server)
    else:
        # Local mode (unchanged)
        from game.application.game_application import GameApplication
        app = GameApplication()
        app.run()


def _run_network_mode(server_uri: str):
    """Network mode: authenticate, lobby, then graphical game."""
    if not server_uri.startswith("ws://") and not server_uri.startswith("wss://"):
        print(f"Error: Invalid server URI: {server_uri}")
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

    # Prompt for credentials
    while True:
        username = input("Username: ")
        if username.strip():
            break
        print("Username cannot be empty.")

    while True:
        password = getpass.getpass("Password: ")
        if password:
            break
        print("Password cannot be empty.")

    # Connect and authenticate
    from game.client.network_transport import NetworkTransport
    from game.client.client_game_state import ClientGameState

    state = ClientGameState()
    outgoing = queue.Queue()
    incoming = queue.Queue()

    transport = NetworkTransport(server_uri, outgoing, incoming)
    transport.start()

    # Send login request
    outgoing.put_nowait(make_login_request(username.strip(), password, action))
    password = None  # noqa: F841

    # Wait for authentication response
    deadline = time.monotonic() + 5.0
    authenticated = False
    auth_error = None
    is_reconnect = False
    leftover_messages = []  # messages from the same batch after login_success

    while time.monotonic() < deadline:
        messages = transport.drain_incoming()
        found = False
        for i, msg in enumerate(messages):
            msg_type = msg.get("type", "")
            payload = msg.get("payload", {})

            if msg_type == "login_success":
                state.apply_login_success(
                    payload.get("color") or None,
                    payload.get("username", ""),
                    payload.get("rating", 1200),
                )
                is_reconnect = payload.get("reconnected", False)
                authenticated = True
                # Keep remaining messages from this batch
                leftover_messages = messages[i + 1:]
                found = True
                break
            elif msg_type == "error":
                auth_error = payload.get("message", "Unknown error")
                found = True
                break

        if found:
            break
        time.sleep(0.05)

    if auth_error:
        print(f"Authentication failed: {auth_error}")
        transport.stop(timeout=2.0)
        return

    if not authenticated:
        error = transport.error or "Connection timeout"
        print(f"Failed to connect: {error}")
        transport.stop(timeout=2.0)
        return

    print(f"Authenticated as '{state.player_username}' (rating: {state.player_rating})")

    # If the server indicated a reconnect, wait for game_state deterministically
    game_ready = False
    if is_reconnect:
        print("Reconnecting to active game...")
        # Check leftover messages from the auth batch first
        for msg in leftover_messages:
            msg_type = msg.get("type", "")
            payload = msg.get("payload", {})
            if msg_type == "game_state":
                state.apply_game_state(
                    payload.get("board", []),
                    payload.get("clock", 0.0),
                    payload.get("white_score", 0),
                    payload.get("black_score", 0),
                    payload.get("game_over", False),
                )
                game_ready = True
                break

        # If not in leftover, poll the transport
        if not game_ready:
            gs_deadline = time.monotonic() + 5.0
            while time.monotonic() < gs_deadline:
                pending_messages = transport.drain_incoming()
                for msg in pending_messages:
                    msg_type = msg.get("type", "")
                    payload = msg.get("payload", {})
                    if msg_type == "game_state":
                        state.apply_game_state(
                            payload.get("board", []),
                            payload.get("clock", 0.0),
                            payload.get("white_score", 0),
                            payload.get("black_score", 0),
                            payload.get("game_over", False),
                        )
                        game_ready = True
                        break
                if game_ready:
                    break
                time.sleep(0.05)

        if game_ready:
            color_name = "White" if state.player_color == "w" else "Black"
            print(f"Reconnected as {color_name}!")
        else:
            print("Failed to receive game state after reconnect.")
            transport.stop(timeout=2.0)
            return
    else:
        # Normal login — terminal lobby
        game_ready = _terminal_lobby(state, outgoing, transport)

    if not game_ready:
        transport.stop(timeout=2.0)
        return

    # Start the graphical game
    from game.client.network_game_application import NetworkGameApplication
    app = NetworkGameApplication.from_transport(
        transport=transport,
        outgoing=outgoing,
        incoming=incoming,
        state=state,
    )
    app.run()


def _terminal_lobby(state, outgoing, transport) -> bool:
    """
    Terminal lobby: matchmaking, room creation, or room join.

    Returns True when the game is ready to start (game_state received).
    """
    while True:
        print("\n--- Lobby ---")
        print("1. Play (matchmaking)")
        print("2. Create Room")
        print("3. Join Room")
        print("4. Exit")
        choice = input("Choose: ").strip()

        if choice == "1":
            if _do_matchmaking(state, outgoing, transport):
                return True
        elif choice == "2":
            if _do_create_room(state, outgoing, transport):
                return True
        elif choice == "3":
            if _do_join_room(state, outgoing, transport):
                return True
        elif choice == "4":
            print("Exiting.")
            return False
        else:
            print("Please enter 1, 2, 3, or 4.")


def _do_matchmaking(state, outgoing, transport) -> bool:
    """Enter matchmaking and wait for a match."""
    outgoing.put_nowait(make_play_request())
    print("Searching for opponent...")

    deadline = time.monotonic() + 65.0  # slightly more than server timeout
    while time.monotonic() < deadline:
        messages = transport.drain_incoming()
        for msg in messages:
            msg_type = msg.get("type", "")
            payload = msg.get("payload", {})

            if msg_type == "matchmaking_started":
                continue
            elif msg_type == "match_found":
                state.apply_match_found(payload)
                print(f"Match found! Opponent: {state.opponent_username}")
                print(f"You are {'White' if state.player_color == 'w' else 'Black'}.")
                continue
            elif msg_type == "game_state":
                state.apply_game_state(
                    payload.get("board", []),
                    payload.get("clock", 0.0),
                    payload.get("white_score", 0),
                    payload.get("black_score", 0),
                    payload.get("game_over", False),
                )
                return True
            elif msg_type == "matchmaking_timeout":
                print("Matchmaking timed out. No compatible opponent found.")
                return False
            elif msg_type == "error":
                print(f"Error: {payload.get('message', 'unknown')}")
                return False
        time.sleep(0.1)

    print("Matchmaking timed out (client-side).")
    return False


def _do_create_room(state, outgoing, transport) -> bool:
    """Create a room and wait for a second player."""
    outgoing.put_nowait(make_create_room())

    deadline = time.monotonic() + 5.0
    room_id = None

    # Wait for room_created
    while time.monotonic() < deadline:
        messages = transport.drain_incoming()
        for msg in messages:
            if msg.get("type") == "room_created":
                room_id = msg.get("payload", {}).get("room_id", "")
                break
            elif msg.get("type") == "error":
                print(f"Error: {msg.get('payload', {}).get('message', 'unknown')}")
                return False
        if room_id:
            break
        time.sleep(0.05)

    if not room_id:
        print("Failed to create room.")
        return False

    print(f"Room created! ID: {room_id}")
    print("Waiting for opponent to join...")

    # Wait for game_state (means second player joined and game is ready)
    deadline = time.monotonic() + 300.0  # 5 minute wait
    while time.monotonic() < deadline:
        messages = transport.drain_incoming()
        for msg in messages:
            msg_type = msg.get("type", "")
            payload = msg.get("payload", {})
            if msg_type == "game_state":
                state.apply_game_state(
                    payload.get("board", []),
                    payload.get("clock", 0.0),
                    payload.get("white_score", 0),
                    payload.get("black_score", 0),
                    payload.get("game_over", False),
                )
                state.player_color = "w"
                print("Opponent joined! Starting game...")
                return True
        time.sleep(0.1)

    print("No one joined. Returning to lobby.")
    return False


def _do_join_room(state, outgoing, transport) -> bool:
    """Join an existing room by ID."""
    room_id = input("Room ID: ").strip()
    if not room_id:
        print("Room ID cannot be empty.")
        return False

    outgoing.put_nowait(make_join_room(room_id))

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        messages = transport.drain_incoming()
        for msg in messages:
            msg_type = msg.get("type", "")
            payload = msg.get("payload", {})

            if msg_type == "room_joined":
                role = payload.get("role", "player")
                color = payload.get("color")
                state.apply_room_joined(room_id, role, color)
                if role == "viewer":
                    print("Joined as viewer.")
                else:
                    color_name = "White" if color == "w" else "Black"
                    print(f"Joined as {color_name}.")
                continue
            elif msg_type == "game_state":
                state.apply_game_state(
                    payload.get("board", []),
                    payload.get("clock", 0.0),
                    payload.get("white_score", 0),
                    payload.get("black_score", 0),
                    payload.get("game_over", False),
                )
                return True
            elif msg_type == "error":
                print(f"Error: {payload.get('message', 'unknown')}")
                return False
        time.sleep(0.05)

    print("Timed out waiting for game state.")
    return False


if __name__ == "__main__":
    main()
