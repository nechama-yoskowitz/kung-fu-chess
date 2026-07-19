"""
Temporary message protocol for the WebSocket server.

Handles message parsing and response construction.
Completely independent from game engine and graphics.
"""

import json


def handle_message(message: str) -> str:
    """
    Process an incoming message and return the response string.

    Protocol:
    - "ping" → "pong"
    - empty → JSON error
    - anything else → JSON echo
    """
    if not message or not message.strip():
        return json.dumps({"type": "error", "message": "empty_message"})

    stripped = message.strip()

    if stripped == "ping":
        return "pong"

    return json.dumps({"type": "echo", "payload": stripped})
