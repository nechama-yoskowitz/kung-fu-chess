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

    def get_pieces_at(r, c):
        return [g for g in gm.graphic_pieces if g.row == r and g.col == c]

    def remove_piece(g):
        gm.graphic_pieces.remove(g)

    gm.get_piece_at = MagicMock(side_effect=get_piece_at)
    gm.get_pieces_at = MagicMock(side_effect=get_pieces_at)
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


# ─── Race condition: animation finishes before move_resolved ──────────────────


class TestAnimationFinishesBeforeMoveResolved:
    """
    The GraphicPiece animation timer completes BEFORE the server sends
    move_resolved. Both the mover and victim end up at the same logical cell.
    """

    def test_mover_before_victim_in_list(self):
        """Mover appears first in graphic_pieces — get_piece_at returns mover."""
        state = ClientGameState()
        state.board = [[".", "wP", ".", "."], [".", "bR", ".", "."]]

        # Mover is FIRST in the list (animation already finished → row/col = dest)
        mover_gp = MagicMock(spec=GraphicPiece)
        mover_gp.piece = "bR"
        mover_gp.row = 0
        mover_gp.col = 1  # Already at destination (animation finished)
        mover_gp.is_moving = False

        victim_gp = MagicMock(spec=GraphicPiece)
        victim_gp.piece = "wP"
        victim_gp.row = 0
        victim_gp.col = 1
        victim_gp.is_moving = False

        gm = MagicMock(spec=GraphicsManager)
        gm.graphic_pieces = [mover_gp, victim_gp]  # mover FIRST

        def get_pieces_at(r, c):
            return [g for g in gm.graphic_pieces if g.row == r and g.col == c]
        def remove_piece(g):
            gm.graphic_pieces.remove(g)
        def fake_finish(r, c):
            mover_gp.row = r
            mover_gp.col = c

        gm.get_pieces_at = MagicMock(side_effect=get_pieces_at)
        gm.get_piece_at = MagicMock(side_effect=lambda r, c: next(
            (g for g in gm.graphic_pieces if g.row == r and g.col == c), None))
        gm.remove_piece = MagicMock(side_effect=remove_piece)
        mover_gp.finish_move_at = MagicMock(side_effect=fake_finish)

        proc = _make_processor(state, gm)
        proc._active_movements[100] = mover_gp
        proc._move_sources[100] = (1, 1)

        proc._on_move_resolved({
            "sequence_id": 100,
            "piece": "bR",
            "outcome": "arrived",
            "final_row": 0,
            "final_col": 1,
            "promoted_to": None,
            "captured_piece": "wP",
        })

        at_dest = [g for g in gm.graphic_pieces if g.row == 0 and g.col == 1]
        assert len(at_dest) == 1
        assert at_dest[0] is mover_gp
        assert victim_gp not in gm.graphic_pieces

    def test_victim_before_mover_in_list(self):
        """Victim appears first in graphic_pieces — get_piece_at returns victim."""
        state = ClientGameState()
        state.board = [[".", "wP", ".", "."], [".", "bR", ".", "."]]

        victim_gp = MagicMock(spec=GraphicPiece)
        victim_gp.piece = "wP"
        victim_gp.row = 0
        victim_gp.col = 1
        victim_gp.is_moving = False

        # Mover already at destination (animation finished)
        mover_gp = MagicMock(spec=GraphicPiece)
        mover_gp.piece = "bR"
        mover_gp.row = 0
        mover_gp.col = 1
        mover_gp.is_moving = False

        gm = MagicMock(spec=GraphicsManager)
        gm.graphic_pieces = [victim_gp, mover_gp]  # victim FIRST

        def get_pieces_at(r, c):
            return [g for g in gm.graphic_pieces if g.row == r and g.col == c]
        def remove_piece(g):
            gm.graphic_pieces.remove(g)
        def fake_finish(r, c):
            mover_gp.row = r
            mover_gp.col = c

        gm.get_pieces_at = MagicMock(side_effect=get_pieces_at)
        gm.get_piece_at = MagicMock(side_effect=lambda r, c: next(
            (g for g in gm.graphic_pieces if g.row == r and g.col == c), None))
        gm.remove_piece = MagicMock(side_effect=remove_piece)
        mover_gp.finish_move_at = MagicMock(side_effect=fake_finish)

        proc = _make_processor(state, gm)
        proc._active_movements[101] = mover_gp
        proc._move_sources[101] = (1, 1)

        proc._on_move_resolved({
            "sequence_id": 101,
            "piece": "bR",
            "outcome": "arrived",
            "final_row": 0,
            "final_col": 1,
            "promoted_to": None,
            "captured_piece": "wP",
        })

        at_dest = [g for g in gm.graphic_pieces if g.row == 0 and g.col == 1]
        assert len(at_dest) == 1
        assert at_dest[0] is mover_gp
        assert victim_gp not in gm.graphic_pieces

    def test_move_resolved_arrives_before_animation(self):
        """Mover is still in-flight when move_resolved arrives (normal fast case)."""
        state = ClientGameState()
        state.board = [[".", "wP", "."], ["bR", ".", "."]]

        victim_gp = MagicMock(spec=GraphicPiece)
        victim_gp.piece = "wP"
        victim_gp.row = 0
        victim_gp.col = 1
        victim_gp.is_moving = False

        mover_gp = MagicMock(spec=GraphicPiece)
        mover_gp.piece = "bR"
        mover_gp.row = 1  # still at source
        mover_gp.col = 0
        mover_gp.is_moving = True

        gm = MagicMock(spec=GraphicsManager)
        gm.graphic_pieces = [victim_gp, mover_gp]

        def get_pieces_at(r, c):
            return [g for g in gm.graphic_pieces if g.row == r and g.col == c]
        def remove_piece(g):
            gm.graphic_pieces.remove(g)
        def fake_finish(r, c):
            mover_gp.row = r
            mover_gp.col = c
            mover_gp.is_moving = False

        gm.get_pieces_at = MagicMock(side_effect=get_pieces_at)
        gm.get_piece_at = MagicMock(side_effect=lambda r, c: next(
            (g for g in gm.graphic_pieces if g.row == r and g.col == c), None))
        gm.remove_piece = MagicMock(side_effect=remove_piece)
        mover_gp.finish_move_at = MagicMock(side_effect=fake_finish)

        proc = _make_processor(state, gm)
        proc._active_movements[102] = mover_gp
        proc._move_sources[102] = (1, 0)

        proc._on_move_resolved({
            "sequence_id": 102,
            "piece": "bR",
            "outcome": "arrived",
            "final_row": 0,
            "final_col": 1,
            "promoted_to": None,
            "captured_piece": "wP",
        })

        at_dest = [g for g in gm.graphic_pieces if g.row == 0 and g.col == 1]
        assert len(at_dest) == 1
        assert at_dest[0] is mover_gp
        assert victim_gp not in gm.graphic_pieces


# ─── Duplicate tokens elsewhere on the board ──────────────────────────────────


class TestDuplicateTokensElsewhere:
    """Other pieces with the same token must not be affected by the capture."""

    def test_other_piece_with_same_token_unaffected(self):
        state = ClientGameState()
        # Two white pawns: one at (0,0), one at (0,2). Black rook captures (0,2).
        state.board = [["wP", ".", "wP", "."], [".", ".", "bR", "."]]

        other_wp = MagicMock(spec=GraphicPiece)
        other_wp.piece = "wP"
        other_wp.row = 0
        other_wp.col = 0
        other_wp.is_moving = False

        victim_wp = MagicMock(spec=GraphicPiece)
        victim_wp.piece = "wP"
        victim_wp.row = 0
        victim_wp.col = 2
        victim_wp.is_moving = False

        mover_gp = MagicMock(spec=GraphicPiece)
        mover_gp.piece = "bR"
        mover_gp.row = 1
        mover_gp.col = 2
        mover_gp.is_moving = True

        gm = MagicMock(spec=GraphicsManager)
        gm.graphic_pieces = [other_wp, victim_wp, mover_gp]

        def get_pieces_at(r, c):
            return [g for g in gm.graphic_pieces if g.row == r and g.col == c]
        def remove_piece(g):
            gm.graphic_pieces.remove(g)
        def fake_finish(r, c):
            mover_gp.row = r
            mover_gp.col = c
            mover_gp.is_moving = False

        gm.get_pieces_at = MagicMock(side_effect=get_pieces_at)
        gm.get_piece_at = MagicMock(side_effect=lambda r, c: next(
            (g for g in gm.graphic_pieces if g.row == r and g.col == c), None))
        gm.remove_piece = MagicMock(side_effect=remove_piece)
        mover_gp.finish_move_at = MagicMock(side_effect=fake_finish)

        proc = _make_processor(state, gm)
        proc._active_movements[200] = mover_gp
        proc._move_sources[200] = (1, 2)

        proc._on_move_resolved({
            "sequence_id": 200,
            "piece": "bR",
            "outcome": "arrived",
            "final_row": 0,
            "final_col": 2,
            "promoted_to": None,
            "captured_piece": "wP",
        })

        # Other wP at (0,0) must be unaffected
        assert other_wp in gm.graphic_pieces
        assert other_wp.row == 0 and other_wp.col == 0

        # Victim removed, mover survived
        assert victim_wp not in gm.graphic_pieces
        assert mover_gp in gm.graphic_pieces


# ─── Promotion with capture ───────────────────────────────────────────────────


class TestPromotionWithCapture:
    """A pawn captures and promotes simultaneously."""

    def test_promotion_capture_leaves_one_promoted_piece(self):
        state = ClientGameState()
        state.board = [[".", "bR", "."], ["wP", ".", "."]]

        victim_gp = MagicMock(spec=GraphicPiece)
        victim_gp.piece = "bR"
        victim_gp.row = 0
        victim_gp.col = 1
        victim_gp.is_moving = False

        mover_gp = MagicMock(spec=GraphicPiece)
        mover_gp.piece = "wP"
        mover_gp.row = 1
        mover_gp.col = 0
        mover_gp.is_moving = True

        gm = MagicMock(spec=GraphicsManager)
        gm.graphic_pieces = [victim_gp, mover_gp]

        def get_pieces_at(r, c):
            return [g for g in gm.graphic_pieces if g.row == r and g.col == c]
        def remove_piece(g):
            gm.graphic_pieces.remove(g)
        def fake_finish(r, c):
            mover_gp.row = r
            mover_gp.col = c
            mover_gp.is_moving = False
        def fake_promote(new_piece):
            mover_gp.piece = new_piece

        gm.get_pieces_at = MagicMock(side_effect=get_pieces_at)
        gm.get_piece_at = MagicMock(side_effect=lambda r, c: next(
            (g for g in gm.graphic_pieces if g.row == r and g.col == c), None))
        gm.remove_piece = MagicMock(side_effect=remove_piece)
        mover_gp.finish_move_at = MagicMock(side_effect=fake_finish)
        mover_gp.promote_to = MagicMock(side_effect=fake_promote)

        proc = _make_processor(state, gm)
        proc._active_movements[300] = mover_gp
        proc._move_sources[300] = (1, 0)

        proc._on_move_resolved({
            "sequence_id": 300,
            "piece": "wP",
            "outcome": "arrived",
            "final_row": 0,
            "final_col": 1,
            "promoted_to": "wQ",
            "captured_piece": "bR",
        })

        at_dest = [g for g in gm.graphic_pieces if g.row == 0 and g.col == 1]
        assert len(at_dest) == 1
        assert at_dest[0] is mover_gp
        assert mover_gp.piece == "wQ"
        assert victim_gp not in gm.graphic_pieces


# ─── Missing tracked mover (client joined late) ──────────────────────────────


class TestMissingTrackedMover:
    """Client missed move_accepted — mover is not in _active_movements."""

    def test_reconciliation_removes_stale_victim_without_tracked_mover(self):
        state = ClientGameState()
        # Board already shows the result: bR captured wP at (0,1)
        state.board = [[".", "bR", "."]]

        victim_gp = MagicMock(spec=GraphicPiece)
        victim_gp.piece = "wP"
        victim_gp.row = 0
        victim_gp.col = 1
        victim_gp.is_moving = False

        # A "mystery" bR appeared (maybe client had it from initial board but
        # didn't track the movement). It's already at dest.
        arrived_gp = MagicMock(spec=GraphicPiece)
        arrived_gp.piece = "bR"
        arrived_gp.row = 0
        arrived_gp.col = 1
        arrived_gp.is_moving = False

        gm = MagicMock(spec=GraphicsManager)
        gm.graphic_pieces = [victim_gp, arrived_gp]

        def get_pieces_at(r, c):
            return [g for g in gm.graphic_pieces if g.row == r and g.col == c]
        def remove_piece(g):
            gm.graphic_pieces.remove(g)

        gm.get_pieces_at = MagicMock(side_effect=get_pieces_at)
        gm.get_piece_at = MagicMock(side_effect=lambda r, c: next(
            (g for g in gm.graphic_pieces if g.row == r and g.col == c), None))
        gm.remove_piece = MagicMock(side_effect=remove_piece)

        proc = _make_processor(state, gm)
        # No entry in _active_movements — mover is unknown

        proc._on_move_resolved({
            "sequence_id": 999,
            "piece": "bR",
            "outcome": "arrived",
            "final_row": 0,
            "final_col": 1,
            "promoted_to": None,
            "captured_piece": "wP",
        })

        # The victim (wP) should be removed by reconciliation
        # The arrived bR should remain (it matches the board)
        at_dest = [g for g in gm.graphic_pieces if g.row == 0 and g.col == 1]
        assert len(at_dest) == 1
        assert at_dest[0].piece == "bR"
        assert victim_gp not in gm.graphic_pieces


# ─── GraphicsManager.get_pieces_at ───────────────────────────────────────────


class TestGetPiecesAt:
    """Verify the new GraphicsManager.get_pieces_at method."""

    def test_returns_all_matching(self):
        from game.graphics.graphics_manager import GraphicsManager

        gm = GraphicsManager.__new__(GraphicsManager)
        gm.graphic_pieces = []

        gp1 = MagicMock(spec=GraphicPiece)
        gp1.row, gp1.col, gp1.piece = 2, 3, "wR"
        gp2 = MagicMock(spec=GraphicPiece)
        gp2.row, gp2.col, gp2.piece = 2, 3, "bP"
        gp3 = MagicMock(spec=GraphicPiece)
        gp3.row, gp3.col, gp3.piece = 0, 0, "wK"

        gm.graphic_pieces = [gp1, gp2, gp3]

        result = gm.get_pieces_at(2, 3)
        assert gp1 in result
        assert gp2 in result
        assert gp3 not in result
        assert len(result) == 2

    def test_returns_empty_when_none(self):
        from game.graphics.graphics_manager import GraphicsManager

        gm = GraphicsManager.__new__(GraphicsManager)
        gm.graphic_pieces = []

        assert gm.get_pieces_at(5, 5) == []
