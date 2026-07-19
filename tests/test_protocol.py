"""
Tests for the multiplayer protocol: serialization, validation, envelope format.
"""

import json

from game.server.protocol import (
    PROTOCOL_VERSION,
    decode_message,
    encode_message,
    make_error,
    make_game_ended,
    make_game_state,
    make_jump_accepted,
    make_jump_rejected,
    make_jump_request,
    make_move_accepted,
    make_move_rejected,
    make_move_request,
    make_move_resolved,
    make_pong,
    validate_jump_request,
    validate_move_request,
)


class TestEnvelope:
    """All messages use a versioned envelope."""

    def test_encode_includes_version(self):
        raw = encode_message("test", {"key": "value"})
        msg = json.loads(raw)
        assert msg["version"] == PROTOCOL_VERSION

    def test_encode_includes_type(self):
        raw = encode_message("move_request", {})
        msg = json.loads(raw)
        assert msg["type"] == "move_request"

    def test_encode_includes_payload(self):
        raw = encode_message("test", {"row": 3})
        msg = json.loads(raw)
        assert msg["payload"]["row"] == 3

    def test_encode_empty_payload_default(self):
        raw = encode_message("pong")
        msg = json.loads(raw)
        assert msg["payload"] == {}

    def test_decode_valid_message(self):
        raw = json.dumps({"version": 1, "type": "ping", "payload": {}})
        msg = decode_message(raw)
        assert msg is not None
        assert msg["type"] == "ping"

    def test_decode_invalid_json(self):
        assert decode_message("not json{{{") is None

    def test_decode_missing_version(self):
        raw = json.dumps({"type": "ping", "payload": {}})
        assert decode_message(raw) is None

    def test_decode_missing_type(self):
        raw = json.dumps({"version": 1, "payload": {}})
        assert decode_message(raw) is None

    def test_decode_non_dict(self):
        assert decode_message(json.dumps([1, 2, 3])) is None

    def test_decode_none_input(self):
        assert decode_message(None) is None


class TestClientMessages:
    """Client → Server message construction."""

    def test_move_request(self):
        raw = make_move_request(6, 4, 4, 4)
        msg = json.loads(raw)
        assert msg["type"] == "move_request"
        assert msg["payload"]["from_row"] == 6
        assert msg["payload"]["from_col"] == 4
        assert msg["payload"]["to_row"] == 4
        assert msg["payload"]["to_col"] == 4

    def test_jump_request(self):
        raw = make_jump_request(3, 5)
        msg = json.loads(raw)
        assert msg["type"] == "jump_request"
        assert msg["payload"]["row"] == 3
        assert msg["payload"]["col"] == 5


class TestServerMessages:
    """Server → Client message construction."""

    def test_game_state(self):
        board = [["wR", ".", "bK"]]
        raw = make_game_state(board, 5000.0, 3, 1, False)
        msg = json.loads(raw)
        assert msg["type"] == "game_state"
        assert msg["payload"]["board"] == [["wR", ".", "bK"]]
        assert msg["payload"]["clock"] == 5000.0
        assert msg["payload"]["white_score"] == 3
        assert msg["payload"]["black_score"] == 1
        assert msg["payload"]["game_over"] is False

    def test_move_accepted(self):
        raw = make_move_accepted(
            sequence_id=7, piece="wR",
            from_row=7, from_col=0, to_row=7, to_col=3,
            started_at=1000.0, arrive_at=4000.0,
        )
        msg = json.loads(raw)
        assert msg["type"] == "move_accepted"
        p = msg["payload"]
        assert p["sequence_id"] == 7
        assert p["piece"] == "wR"
        assert p["arrive_at"] == 4000.0

    def test_move_rejected(self):
        raw = make_move_rejected("illegal_piece_move", 6, 4, 3, 3)
        msg = json.loads(raw)
        assert msg["type"] == "move_rejected"
        assert msg["payload"]["reason"] == "illegal_piece_move"

    def test_move_resolved(self):
        raw = make_move_resolved(
            sequence_id=5, piece="wP", outcome="arrived",
            final_row=0, final_col=0, promoted_to="wQ",
            captured_piece="bR",
        )
        msg = json.loads(raw)
        assert msg["type"] == "move_resolved"
        p = msg["payload"]
        assert p["outcome"] == "arrived"
        assert p["promoted_to"] == "wQ"
        assert p["captured_piece"] == "bR"

    def test_jump_accepted(self):
        raw = make_jump_accepted("wR", 3, 5, 6500.0)
        msg = json.loads(raw)
        assert msg["type"] == "jump_accepted"
        assert msg["payload"]["expires_at"] == 6500.0

    def test_jump_rejected(self):
        raw = make_jump_rejected("piece_moving", 3, 5)
        msg = json.loads(raw)
        assert msg["type"] == "jump_rejected"
        assert msg["payload"]["reason"] == "piece_moving"

    def test_game_ended(self):
        raw = make_game_ended("w", "b")
        msg = json.loads(raw)
        assert msg["type"] == "game_ended"
        assert msg["payload"]["winner"] == "w"
        assert msg["payload"]["loser"] == "b"

    def test_pong(self):
        raw = make_pong()
        msg = json.loads(raw)
        assert msg["type"] == "pong"

    def test_error(self):
        raw = make_error("invalid move format", "validation_error")
        msg = json.loads(raw)
        assert msg["type"] == "error"
        assert msg["payload"]["code"] == "validation_error"
        assert msg["payload"]["message"] == "invalid move format"


class TestValidation:
    """Payload validation catches missing/invalid fields."""

    def test_valid_move_request(self):
        payload = {"from_row": 6, "from_col": 4, "to_row": 4, "to_col": 4}
        assert validate_move_request(payload) is None

    def test_move_missing_field(self):
        payload = {"from_row": 6, "from_col": 4, "to_row": 4}
        err = validate_move_request(payload)
        assert "to_col" in err

    def test_move_non_integer_field(self):
        payload = {"from_row": "6", "from_col": 4, "to_row": 4, "to_col": 4}
        err = validate_move_request(payload)
        assert "integer" in err

    def test_valid_jump_request(self):
        payload = {"row": 3, "col": 5}
        assert validate_jump_request(payload) is None

    def test_jump_missing_field(self):
        payload = {"row": 3}
        err = validate_jump_request(payload)
        assert "col" in err

    def test_jump_non_integer_field(self):
        payload = {"row": 3, "col": 5.5}
        err = validate_jump_request(payload)
        assert "integer" in err


class TestUnknownMessageType:
    """Unknown message types are decodable but not in known sets."""

    def test_unknown_type_still_decodes(self):
        raw = json.dumps({"version": 1, "type": "unknown_xyz", "payload": {}})
        msg = decode_message(raw)
        assert msg is not None
        assert msg["type"] == "unknown_xyz"


class TestRoundTrip:
    """Messages survive encode → decode round trip."""

    def test_move_request_round_trip(self):
        raw = make_move_request(6, 4, 4, 4)
        msg = decode_message(raw)
        assert msg["type"] == "move_request"
        assert msg["payload"]["from_row"] == 6

    def test_game_state_round_trip(self):
        board = [["wR", ".", ".", "bK"], [".", "wP", ".", "."]]
        raw = make_game_state(board, 12345.0, 5, 9, True)
        msg = decode_message(raw)
        assert msg["payload"]["board"] == board
        assert msg["payload"]["game_over"] is True
