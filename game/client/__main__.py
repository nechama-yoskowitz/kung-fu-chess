"""
Entry point: python -m game.client

Connects to the local WebSocket server and provides an interactive console.
Prompts for a username before joining the game.
"""

import asyncio

from game.client.websocket_client import run_client, DEFAULT_URI


def main():
    print("Kung-Fu Chess Client")
    print(f"Connecting to {DEFAULT_URI}...")
    asyncio.run(run_client(uri=DEFAULT_URI))


if __name__ == "__main__":
    main()
