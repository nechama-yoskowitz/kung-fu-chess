"""
Minimal console WebSocket client for Kung-Fu Chess.

Connects to the server, sends user input, and prints responses.
"""

import asyncio

import websockets

DEFAULT_URI = "ws://localhost:8765"


async def run_client(uri: str = DEFAULT_URI) -> None:
    """Connect to the server and enter an interactive send/receive loop."""
    try:
        async with websockets.connect(uri) as ws:
            print(f"Connected to {uri}")
            print("Type messages to send. Type 'quit' to exit.\n")

            while True:
                message = await asyncio.get_event_loop().run_in_executor(
                    None, input, "> "
                )

                if message.strip().lower() == "quit":
                    print("Disconnecting...")
                    break

                await ws.send(message)
                response = await ws.recv()
                print(f"< {response}")

    except (ConnectionRefusedError, OSError) as e:
        print(f"Error: Could not connect to server at {uri}")
        print(f"  {e}")
        print("Make sure the server is running: python -m game.server")
