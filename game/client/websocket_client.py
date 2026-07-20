"""
Minimal console WebSocket client for Kung-Fu Chess.

Connects to the server, performs register/login, then enters interactive play.
"""

import asyncio
import getpass
import json

import websockets

from game.server.protocol import decode_message, make_login_request

DEFAULT_URI = "ws://localhost:8765"


def prompt_credentials() -> tuple[str, str, str]:
    """
    Ask the user whether to register or login, then collect username and password.

    Returns (action, username, password).
    Password is collected via getpass so it is not echoed.
    """
    # Choose action
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

    # Username
    while True:
        username = input("Username: ")
        if username.strip():
            break
        print("Username cannot be empty.")

    # Password (not echoed)
    while True:
        password = getpass.getpass("Password: ")
        if password:
            break
        print("Password cannot be empty.")

    return action, username.strip(), password


async def run_client(uri: str = DEFAULT_URI,
                     username: str | None = None,
                     password: str | None = None,
                     action: str | None = None) -> None:
    """
    Connect to the server, register or login, and enter interactive mode.

    Parameters
    ----------
    uri : str
        WebSocket server URI.
    username, password, action : str | None
        If all provided, skip interactive prompts (useful for testing/scripting).
    """
    if username is None or password is None or action is None:
        action, username, password = prompt_credentials()

    try:
        async with websockets.connect(uri) as ws:
            print(f"Connected to {uri}")

            # Send login request
            await ws.send(make_login_request(username, password, action))

            # Do not retain password in memory after sending
            password = None  # noqa: F841

            response_raw = await ws.recv()
            response = decode_message(response_raw)

            if response is None:
                print(f"Unexpected server response: {response_raw}")
                return

            if response["type"] == "error":
                code = response["payload"].get("code", "")
                message = response["payload"].get("message", "")
                print(f"Login failed: {message} ({code})")
                return

            if response["type"] == "login_success":
                color = response["payload"]["color"]
                color_name = "White" if color == "w" else "Black"
                server_username = response["payload"].get("username", username)
                print(f"Logged in as '{server_username}' - you are {color_name}.")
            else:
                print(f"Unexpected response: {response_raw}")
                return

            # Receive game_state
            state_raw = await ws.recv()
            state_msg = decode_message(state_raw)
            if state_msg and state_msg["type"] == "game_state":
                print("Game state received. Ready to play!")
            else:
                print(f"< {state_raw}")

            print("Type commands to send. Type 'quit' to exit.\n")

            while True:
                message = await asyncio.get_event_loop().run_in_executor(
                    None, input, "> "
                )

                if message.strip().lower() == "quit":
                    print("Disconnecting...")
                    break

                await ws.send(message)
                resp = await ws.recv()
                print(f"< {resp}")

    except (ConnectionRefusedError, OSError) as e:
        print(f"Error: Could not connect to server at {uri}")
        print(f"  {e}")
        print("Make sure the server is running: python -m game.server")
