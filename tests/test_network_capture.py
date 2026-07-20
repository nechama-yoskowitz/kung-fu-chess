"""
Regression tests for the network capture rendering bug.

Verifies that ServerMessageProcessor correctly removes victim GraphicPieces
when a move resolves with a capture, and that only the surviving piece
remains at the destination.
"""

from unittest.mock import MagicMock

from game.client.client_game_state import ClientGameState
from game.client.server_message_processor import ServerMessageProcessor
from game.events import EventBus
from game.graphics.graphics_manager import GraphicsManager
from game.graphics.pieces.graphic_piece import GraphicPiece


def _make_gm_with_pieces(pieces_spec):
    """
    Create a GraphicsManager with mock pieces at given positions.

    pieces_spec: list of (piece_token, row, col)
    Returns (gm, {(row,col): GraphicPiece})
    """
    gm = MagicMock(spec=GraphicsManager)
    gp_list = []
    gp_map = {}

    for token, row, col in pieces_spec:
        gp = MagicMock(spec=GraphicPiece)
        gp.piece = token
        gp.row = row
        gp.col = col
        gp.is_moving = False
        gp.state = "idle"
        gp_list.append(gp)
        gp_map[(row, col)] = gp

    gm.graphic_pieces = gp_list

    def get_piece_at(r, c):
        for g in gm.graphic_pieces:
            if g.row == r and g.col == c:
                return g
        return None

    def remove_piece(g):
        gm.graphic_pieces.remove(g)

    gm.get_piece_at = MagicMock(side_effect=get_piece_at)
    gm.remove_piece = MagicMock(side_effect=remove_piece)

    return gm, gp_map


def _make_processor(state, gm):
    return ServerMessageProcessor(
        state=state,
        graphics_manager=gm,
        event_bus=EventBus(),
    )


# ─── Successful capture: mover captures stationary victim ─────────────────────


class TestMoverCapturesVictim:
    """Black pawn captures white pawn at destination."""

    def test_victim_gp_removed_after_capture(self):
        state = ClientGameState()
        state.board = [
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", "wP", ".", ".", "."],
            [".", ".", ".", ".", ".", "bP", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
        ]

        gm, gp_map = _make_gm_with_pieces([
            ("wP", 3, 4),  # victim at destination
            ("bP", 4, 5),  # mover (will be tracked as moving)
        ])

        # Mark mover as moving
        mover_gp = gp_map[(4, 5)]
        mover_gp.is_moving = True

        proc = _make_processor(state, gm)

        # Simulate move_accepted: track the mover
        proc._active_movements[1] = mover_gp
        proc._move_sources[1] = (4, 5)

        # Simulate move_resolved: bP captures wP at (3,4)
        proc._on_move_resolved({
            "sequence_id": 1,
            "piece": "bP",
            "outcome": "arrived",
            "final_row": 3,
            "final_col": 4,
            "promoted_to": None,
            "captured_piece": "wP",
        })

        # Victim must have been removed
        gm.remove_piece.assert_called()
        removed_pieces = [call.args[0] for call in gm.remove_piece.call_args_list]
        assert gp_map[(3, 4)] in removed_pieces

    def test_mover_gp_survives_after_capture(self):
        state = ClientGameState()
        state.board = [[".", "wP"], ["bP", "."]]

        gm, gp_map = _make_gm_with_pieces([
            ("wP", 0, 1),  # victim
            ("bP", 1, 0),  # mover
        ])

        mover_gp = gp_map[(1, 0)]
        mover_gp.is_moving = True

        proc = _make_processor(state, gm)
        proc._active_movements[5] = mover_gp
        proc._move_sources[5] = (1, 0)

        proc._on_move_resolved({
            "sequence_id": 5,
            "piece": "bP",
            "outcome": "arrived",
            "final_row": 0,
            "final_col": 1,
            "promoted_to": None,
            "captured_piece": "wP",
        })

        # Mover must still exist in graphic_pieces
        assert mover_gp in gm.graphic_pieces

    def test_exactly_one_gp_at_destination_after_capture(self):
        state = ClientGameState()
        state.board = [[".", "wR", ".", "."], ["bR", ".", ".", "."]]

        gm, gp_map = _make_gm_with_pieces([
            ("wR", 0, 1),  # victim
            ("bR", 1, 0),  # mover
        ])

        mover_gp = gp_map[(1, 0)]
        mover_gp.is_moving = True

        # Make finish_move_at update row/col on the mock
        def fake_finish(row, col):
            mover_gp.row = row
            mover_gp.col = col
            mover_gp.is_moving = False
        mover_gp.finish_move_at = MagicMock(side_effect=fake_finish)

        proc = _make_processor(state, gm)
        proc._active_movements[10] = mover_gp
        proc._move_sources[10] = (1, 0)

        proc._on_move_resolved({
            "sequence_id": 10,
            "piece": "bR",
            "outcome": "arrived",
            "final_row": 0,
            "final_col": 1,
            "promoted_to": None,
            "captured_piece": "wR",
        })

        # Only one GP at (0,1) — the mover
        at_dest = [g for g in gm.graphic_pieces if g.row == 0 and g.col == 1]
        assert len(at_dest) == 1
        assert at_dest[0] is mover_gp

    def test_board_state_matches_after_capture(self):
        state = ClientGameState()
        state.board = [[".", "wP"], ["bP", "."]]

        gm, gp_map = _make_gm_with_pieces([
            ("wP", 0, 1),
            ("bP", 1, 0),
        ])

        mover_gp = gp_map[(1, 0)]
        mover_gp.is_moving = True

        proc = _make_processor(state, gm)
        proc._active_movements[7] = mover_gp
        proc._move_sources[7] = (1, 0)

        proc._on_move_resolved({
            "sequence_id": 7,
            "piece": "bP",
            "outcome": "arrived",
            "final_row": 0,
            "final_col": 1,
            "promoted_to": None,
            "captured_piece": "wP",
        })

        # Board: source cleared, dest has mover
        assert state.board[1][0] == "."
        assert state.board[0][1] == "bP"

    def test_captured_piece_does_not_reappear_after_mover_leaves(self):
        """Simulate: bP captures wP, then bP moves away. wP must not reappear."""
        state = ClientGameState()
        state.board = [[".", "wP", "."], ["bP", ".", "."], [".", ".", "."]]

        gm, gp_map = _make_gm_with_pieces([
            ("wP", 0, 1),
            ("bP", 1, 0),
        ])

        mover_gp = gp_map[(1, 0)]
        mover_gp.is_moving = True

        proc = _make_processor(state, gm)
        proc._active_movements[1] = mover_gp
        proc._move_sources[1] = (1, 0)

        # First move: bP captures wP at (0,1)
        proc._on_move_resolved({
            "sequence_id": 1,
            "piece": "bP",
            "outcome": "arrived",
            "final_row": 0,
            "final_col": 1,
            "promoted_to": None,
            "captured_piece": "wP",
        })

        # Simulate mover_gp is now at (0,1) after finish_move_at
        mover_gp.row = 0
        mover_gp.col = 1
        mover_gp.is_moving = False

        # Second move: bP moves from (0,1) to (0,2)
        mover_gp.is_moving = True
        proc._active_movements[2] = mover_gp
        proc._move_sources[2] = (0, 1)

        proc._on_move_resolved({
            "sequence_id": 2,
            "piece": "bP",
            "outcome": "arrived",
            "final_row": 0,
            "final_col": 2,
            "promoted_to": None,
            "captured_piece": None,
        })

        mover_gp.row = 0
        mover_gp.col = 2

        # No GP should remain at (0,1) — victim was removed in the first move
        at_old_dest = [g for g in gm.graphic_pieces if g.row == 0 and g.col == 1]
        assert len(at_old_dest) == 0


# ─── Moving piece gets captured (e.g. by airborne defender) ───────────────────


class TestMoverGetsCaptured:
    """The moving piece itself is destroyed (outcome='captured')."""

    def test_mover_removed_when_captured(self):
        state = ClientGameState()
        state.board = [["wR", ".", ".", "bP"]]

        gm, gp_map = _make_gm_with_pieces([
            ("wR", 0, 0),  # mover that gets captured
            ("bP", 0, 3),  # airborne defender (stays)
        ])

        mover_gp = gp_map[(0, 0)]
        mover_gp.is_moving = True

        proc = _make_processor(state, gm)
        proc._active_movements[20] = mover_gp
        proc._move_sources[20] = (0, 0)

        proc._on_move_resolved({
            "sequence_id": 20,
            "piece": "wR",
            "outcome": "captured",
            "final_row": None,
            "final_col": None,
            "promoted_to": None,
            "captured_piece": "wR",
        })

        # Mover must be removed
        gm.remove_piece.assert_called_once_with(mover_gp)
        assert mover_gp not in gm.graphic_pieces

    def test_surviving_piece_remains_when_mover_captured(self):
        state = ClientGameState()
        state.board = [["wR", ".", ".", "bP"]]

        gm, gp_map = _make_gm_with_pieces([
            ("wR", 0, 0),
            ("bP", 0, 3),
        ])

        mover_gp = gp_map[(0, 0)]
        mover_gp.is_moving = True

        proc = _make_processor(state, gm)
        proc._active_movements[21] = mover_gp
        proc._move_sources[21] = (0, 0)

        proc._on_move_resolved({
            "sequence_id": 21,
            "piece": "wR",
            "outcome": "captured",
            "final_row": None,
            "final_col": None,
            "promoted_to": None,
            "captured_piece": "wR",
        })

        # The defender (bP) must still be in graphic_pieces
        assert gp_map[(0, 3)] in gm.graphic_pieces


# ─── White captures black (symmetric) ────────────────────────────────────────


class TestWhiteCapturesBlack:
    """White piece captures black — same logic, opposite colors."""

    def test_white_rook_captures_black_pawn(self):
        state = ClientGameState()
        state.board = [["wR", ".", "bP", "."]]

        gm, gp_map = _make_gm_with_pieces([
            ("wR", 0, 0),
            ("bP", 0, 2),
        ])

        mover_gp = gp_map[(0, 0)]
        mover_gp.is_moving = True

        # Make finish_move_at update row/col on the mock
        def fake_finish(row, col):
            mover_gp.row = row
            mover_gp.col = col
            mover_gp.is_moving = False
        mover_gp.finish_move_at = MagicMock(side_effect=fake_finish)

        proc = _make_processor(state, gm)
        proc._active_movements[30] = mover_gp
        proc._move_sources[30] = (0, 0)

        proc._on_move_resolved({
            "sequence_id": 30,
            "piece": "wR",
            "outcome": "arrived",
            "final_row": 0,
            "final_col": 2,
            "promoted_to": None,
            "captured_piece": "bP",
        })

        # Victim (bP) removed, mover (wR) survives
        assert gp_map[(0, 2)] not in gm.graphic_pieces
        assert mover_gp in gm.graphic_pieces

        # Exactly one GP at destination
        at_dest = [g for g in gm.graphic_pieces if g.row == 0 and g.col == 2]
        assert len(at_dest) == 1
