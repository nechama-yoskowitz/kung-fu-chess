"""
Kung-Fu Chess multiplayer protocol.

Defines the JSON message format exchanged between client and server over WebSocket.

Design decisions:
- Server is authoritative: client sends commands, server validates and broadcasts state.
- State sync uses full board snapshots on connect + incremental events during play.
  This avoids missed-event desynchronization without sending the full board every frame.
- All messages use a versioned envelope: {"version": 1, "type": "...", "payload": {...}}
- Coordinates are (row, col) integers, 0-indexed from top-left.
- Piece tokens use the engine format: "wR", "bP", etc.
- Timestamps are engine clock values in milliseconds (float).
"""

import json
from dataclasses import dataclass, asdict
from typing import Any

PROTOCOL_VERSION = 1


# ─── Envelope ──────────────────────────────────────────────────────────────────


def encode_message(msg_type: str, payload: dict | None = None) -> str:
    """Serialize a protocol message to JSON string."""
    envelope = {
        "version": PROTOCOL_VERSION,
        "type": msg_type,
        "payload": payload or {},
    }
    return json.dumps(envelope)


def decode_message(raw: str) -> dict | None:
    """
    Deserialize a JSON protocol message.

    Returns the parsed dict with "version", "type", "payload" keys,
    or None if the message is malformed.
    """
    try:
        msg = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(msg, dict):
        return None

    if "version" not in msg or "type" not in msg:
        return None

    return msg


def make_error(message: str, code: str = "protocol_error") -> str:
    """Create an error response message."""
    return encode_message("error", {"code": code, "message": message})


# ─── Client → Server message types ────────────────────────────────────────────

# login_request: client sends a username to join the game
# move_request: client asks to move a piece
# jump_request: client asks to jump a piece
# ping: keepalive

CLIENT_MESSAGE_TYPES = {"login_request", "move_request", "jump_request",
                        "play_request", "cancel_matchmaking",
                        "create_room", "join_room", "ping"}


# ─── Server → Client message types ────────────────────────────────────────────

# login_success: confirms login, includes assigned color and username
# game_state: full board snapshot (sent on connect and periodically if needed)
# move_accepted: confirms a move was started, includes timing data
# move_rejected: explains why a move failed
# move_resolved: a pending move reached its outcome
# jump_accepted: confirms a jump was started
# jump_rejected: explains why a jump failed
# game_ended: the game is over
# pong: keepalive response
# error: protocol-level error

SERVER_MESSAGE_TYPES = {
    "login_success", "game_state", "move_accepted", "move_rejected",
    "move_resolved", "jump_accepted", "jump_rejected",
    "game_ended", "rating_updated",
    "matchmaking_started", "match_found", "matchmaking_timeout",
    "matchmaking_cancelled",
    "room_created", "room_joined", "room_not_found", "room_full",
    "player_disconnected", "reconnect_countdown", "player_reconnected",
    "pong", "error",
}


# ─── Payload schemas ──────────────────────────────────────────────────────────


def make_login_request(username: str, password: str, action: str = "login") -> str:
    """Client → Server: request login or registration with credentials."""
    return encode_message("login_request", {
        "action": action,
        "username": username,
        "password": password,
    })


def make_login_success(username: str, color: str, rating: int = 1200,
                       reconnected: bool = False) -> str:
    """Server → Client: login accepted, color assigned, rating included."""
    return encode_message("login_success", {
        "username": username,
        "color": color,
        "rating": rating,
        "reconnected": reconnected,
    })


def make_move_request(from_row: int, from_col: int, to_row: int, to_col: int) -> str:
    """Client → Server: request a move."""
    return encode_message("move_request", {
        "from_row": from_row,
        "from_col": from_col,
        "to_row": to_row,
        "to_col": to_col,
    })


def make_jump_request(row: int, col: int) -> str:
    """Client → Server: request a jump."""
    return encode_message("jump_request", {
        "row": row,
        "col": col,
    })


def make_game_state(board: list[list[str]], clock: float,
                    white_score: int, black_score: int,
                    game_over: bool) -> str:
    """Server → Client: full board snapshot."""
    return encode_message("game_state", {
        "board": board,
        "clock": clock,
        "white_score": white_score,
        "black_score": black_score,
        "game_over": game_over,
    })


def make_move_accepted(sequence_id: int, piece: str,
                       from_row: int, from_col: int,
                       to_row: int, to_col: int,
                       started_at: float, arrive_at: float) -> str:
    """Server → Client: move was validated and started."""
    return encode_message("move_accepted", {
        "sequence_id": sequence_id,
        "piece": piece,
        "from_row": from_row,
        "from_col": from_col,
        "to_row": to_row,
        "to_col": to_col,
        "started_at": started_at,
        "arrive_at": arrive_at,
    })


def make_move_rejected(reason: str, from_row: int, from_col: int,
                       to_row: int, to_col: int) -> str:
    """Server → Client: move was rejected."""
    return encode_message("move_rejected", {
        "reason": reason,
        "from_row": from_row,
        "from_col": from_col,
        "to_row": to_row,
        "to_col": to_col,
    })


def make_move_resolved(sequence_id: int, piece: str, outcome: str,
                       final_row: int | None, final_col: int | None,
                       promoted_to: str | None,
                       captured_piece: str | None) -> str:
    """Server → Client: a move reached its final outcome."""
    return encode_message("move_resolved", {
        "sequence_id": sequence_id,
        "piece": piece,
        "outcome": outcome,
        "final_row": final_row,
        "final_col": final_col,
        "promoted_to": promoted_to,
        "captured_piece": captured_piece,
    })


def make_jump_accepted(piece: str, row: int, col: int, expires_at: float) -> str:
    """Server → Client: jump was validated and started."""
    return encode_message("jump_accepted", {
        "piece": piece,
        "row": row,
        "col": col,
        "expires_at": expires_at,
    })


def make_jump_rejected(reason: str, row: int, col: int) -> str:
    """Server → Client: jump was rejected."""
    return encode_message("jump_rejected", {
        "reason": reason,
        "row": row,
        "col": col,
    })


def make_game_ended(winner: str, loser: str) -> str:
    """Server → Client: game over."""
    return encode_message("game_ended", {
        "winner": winner,
        "loser": loser,
    })


def make_rating_updated(username: str, old_rating: int, new_rating: int, change: int) -> str:
    """Server → Client: a player's rating was updated after a game."""
    return encode_message("rating_updated", {
        "username": username,
        "old_rating": old_rating,
        "new_rating": new_rating,
        "change": change,
    })


def make_pong() -> str:
    """Server → Client: keepalive response."""
    return encode_message("pong")


# ─── Matchmaking messages ─────────────────────────────────────────────────────


def make_play_request() -> str:
    """Client → Server: request to enter matchmaking."""
    return encode_message("play_request")


def make_cancel_matchmaking() -> str:
    """Client → Server: cancel matchmaking."""
    return encode_message("cancel_matchmaking")


def make_matchmaking_started() -> str:
    """Server → Client: player has entered the matchmaking queue."""
    return encode_message("matchmaking_started")


def make_match_found(
    opponent_username: str,
    color: str,
    own_rating: int,
    opponent_rating: int,
) -> str:
    """Server → Client: a match was found."""
    return encode_message("match_found", {
        "opponent_username": opponent_username,
        "color": color,
        "own_rating": own_rating,
        "opponent_rating": opponent_rating,
    })


def make_matchmaking_timeout() -> str:
    """Server → Client: matchmaking timed out (no compatible opponent found)."""
    return encode_message("matchmaking_timeout")


def make_matchmaking_cancelled() -> str:
    """Server → Client: matchmaking was cancelled by the player."""
    return encode_message("matchmaking_cancelled")


# ─── Room messages ────────────────────────────────────────────────────────────


def make_create_room() -> str:
    """Client → Server: request to create a new room."""
    return encode_message("create_room")


def make_join_room(room_id: str) -> str:
    """Client → Server: request to join a room by ID."""
    return encode_message("join_room", {"room_id": room_id})


def make_room_created(room_id: str) -> str:
    """Server → Client: room was created, includes the room ID."""
    return encode_message("room_created", {"room_id": room_id})


def make_room_joined(room_id: str, color: str | None, role: str = "player") -> str:
    """Server → Client: successfully joined a room."""
    return encode_message("room_joined", {
        "room_id": room_id,
        "role": role,
        "color": color,
    })


# ─── Reconnect messages ───────────────────────────────────────────────────────


def make_player_disconnected(username: str, color: str, remaining_seconds: int) -> str:
    """Server → Client: a player has disconnected, countdown started."""
    return encode_message("player_disconnected", {
        "username": username,
        "color": color,
        "remaining_seconds": remaining_seconds,
    })


def make_reconnect_countdown(username: str, color: str, remaining_seconds: int) -> str:
    """Server → Client: countdown update for disconnected player."""
    return encode_message("reconnect_countdown", {
        "username": username,
        "color": color,
        "remaining_seconds": remaining_seconds,
    })


def make_player_reconnected(username: str, color: str) -> str:
    """Server → Client: a disconnected player has reconnected."""
    return encode_message("player_reconnected", {
        "username": username,
        "color": color,
    })


# ─── Validation ───────────────────────────────────────────────────────────────


def validate_move_request(payload: dict) -> str | None:
    """Return error message if payload is invalid, None if valid."""
    for field in ("from_row", "from_col", "to_row", "to_col"):
        if field not in payload:
            return f"missing field: {field}"
        if not isinstance(payload[field], int):
            return f"field {field} must be an integer"
    return None


def validate_jump_request(payload: dict) -> str | None:
    """Return error message if payload is invalid, None if valid."""
    for field in ("row", "col"):
        if field not in payload:
            return f"missing field: {field}"
        if not isinstance(payload[field], int):
            return f"field {field} must be an integer"
    return None


def validate_login_request(payload: dict) -> str | None:
    """Return error message if payload is invalid, None if valid."""
    # Action field
    if "action" not in payload:
        return "missing field: action"
    action = payload["action"]
    if not isinstance(action, str):
        return "action must be a string"
    if action not in ("login", "register"):
        return f"unsupported action: {action}"

    # Username field
    if "username" not in payload:
        return "missing field: username"
    username = payload["username"]
    if not isinstance(username, str):
        return "username must be a string"
    if not username.strip():
        return "username must not be empty or whitespace-only"

    # Password field
    if "password" not in payload:
        return "missing field: password"
    password = payload["password"]
    if not isinstance(password, str):
        return "password must be a string"
    if not password:
        return "password must not be empty"

    return None
