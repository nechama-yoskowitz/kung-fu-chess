"""
Focused tests for ELO rating updates.

Covers:
- EloCalculator: equal ratings, higher beats lower, lower beats higher, immutability
- UserRepository.update_rating: persists correctly
- RatingService: both players persisted, once-only, missing players, no winner
- Protocol: rating_updated message format
- Client: updates only own rating
"""

from unittest.mock import MagicMock

import pytest

from game.client.client_game_state import ClientGameState
from game.client.server_message_processor import ServerMessageProcessor
from game.graphics.graphics_manager import GraphicsManager
from game.server.auth.user_repository import UserRepository
from game.server.auth.user_service import UserService
from game.server.protocol import decode_message, make_rating_updated
from game.server.rating.elo_calculator import EloCalculator
from game.server.rating.rating_service import RatingService


# ─── EloCalculator ────────────────────────────────────────────────────────────


class TestEloCalculatorEqualRatings:
    def test_equal_ratings_winner_gains(self):
        calc = EloCalculator(k_factor=32)
        new_w, new_l = calc.calculate(1200, 1200)
        assert new_w == 1216

    def test_equal_ratings_loser_loses(self):
        calc = EloCalculator(k_factor=32)
        new_w, new_l = calc.calculate(1200, 1200)
        assert new_l == 1184

    def test_equal_ratings_symmetric(self):
        calc = EloCalculator(k_factor=32)
        new_w, new_l = calc.calculate(1200, 1200)
        assert new_w - 1200 == -(new_l - 1200)


class TestEloCalculatorUnequalRatings:
    def test_higher_rated_beats_lower(self):
        calc = EloCalculator(k_factor=32)
        new_w, new_l = calc.calculate(1400, 1200)
        # Higher-rated winner gains less
        assert new_w > 1400
        assert new_w - 1400 < 16  # gains less than half of K
        assert new_l < 1200

    def test_lower_rated_beats_higher(self):
        calc = EloCalculator(k_factor=32)
        new_w, new_l = calc.calculate(1200, 1400)
        # Lower-rated winner gains more (upset)
        assert new_w > 1200
        assert new_w - 1200 > 16  # gains more than half of K
        assert new_l < 1400

    def test_large_gap_winner_gains_almost_full_k(self):
        calc = EloCalculator(k_factor=32)
        new_w, _ = calc.calculate(800, 1600)
        # Massive upset — winner gains close to 32
        assert new_w - 800 > 28


class TestEloCalculatorImmutability:
    def test_does_not_mutate_inputs(self):
        calc = EloCalculator(k_factor=32)
        w_rating = 1200
        l_rating = 1300
        calc.calculate(w_rating, l_rating)
        assert w_rating == 1200
        assert l_rating == 1300

    def test_returns_integers(self):
        calc = EloCalculator(k_factor=32)
        new_w, new_l = calc.calculate(1200, 1200)
        assert isinstance(new_w, int)
        assert isinstance(new_l, int)

    def test_k_factor_configurable(self):
        calc = EloCalculator(k_factor=16)
        new_w, new_l = calc.calculate(1200, 1200)
        assert new_w == 1208
        assert new_l == 1192


# ─── UserRepository.update_rating ─────────────────────────────────────────────


class TestRepositoryUpdateRating:
    def test_updates_rating(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        repo.create_user("alice", "hash", rating=1200)

        repo.update_rating("alice", 1216)

        user = repo.get_user_by_username("alice")
        assert user.rating == 1216

    def test_update_nonexistent_raises(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()

        with pytest.raises(ValueError, match="User not found"):
            repo.update_rating("ghost", 1300)

    def test_update_preserves_other_fields(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        repo.create_user("bob", "myhash", rating=1200)

        repo.update_rating("bob", 1250)

        user = repo.get_user_by_username("bob")
        assert user.username == "bob"
        assert user.password_hash == "myhash"
        assert user.rating == 1250


# ─── RatingService ────────────────────────────────────────────────────────────


class TestRatingServiceSuccess:
    def test_both_players_updated(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        repo.create_user("winner", "h", rating=1200)
        repo.create_user("loser", "h", rating=1200)

        svc = RatingService(repository=repo)
        result = svc.process_game_end("game-1", "winner", "loser")

        assert result is not None
        assert result.winner.username == "winner"
        assert result.winner.new_rating == 1216
        assert result.loser.username == "loser"
        assert result.loser.new_rating == 1184

    def test_persistence_after_update(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        repo.create_user("alice", "h", rating=1200)
        repo.create_user("bob", "h", rating=1200)

        svc = RatingService(repository=repo)
        svc.process_game_end("game-2", "alice", "bob")

        assert repo.get_user_by_username("alice").rating == 1216
        assert repo.get_user_by_username("bob").rating == 1184

    def test_result_contains_correct_changes(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        repo.create_user("pro", "h", rating=1500)
        repo.create_user("noob", "h", rating=1000)

        svc = RatingService(repository=repo)
        result = svc.process_game_end("game-3", "noob", "pro")

        # Upset: noob wins
        assert result.winner.change > 0
        assert result.loser.change < 0
        assert result.winner.old_rating == 1000
        assert result.loser.old_rating == 1500


class TestRatingServiceOnceOnly:
    def test_duplicate_game_id_returns_none(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        repo.create_user("a", "h", rating=1200)
        repo.create_user("b", "h", rating=1200)

        svc = RatingService(repository=repo)
        result1 = svc.process_game_end("game-dup", "a", "b")
        result2 = svc.process_game_end("game-dup", "a", "b")

        assert result1 is not None
        assert result2 is None

    def test_duplicate_does_not_double_update(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        repo.create_user("x", "h", rating=1200)
        repo.create_user("y", "h", rating=1200)

        svc = RatingService(repository=repo)
        svc.process_game_end("game-once", "x", "y")
        svc.process_game_end("game-once", "x", "y")

        assert repo.get_user_by_username("x").rating == 1216
        assert repo.get_user_by_username("y").rating == 1184


class TestRatingServiceGuards:
    def test_missing_winner_username(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        repo.create_user("only", "h", rating=1200)

        svc = RatingService(repository=repo)
        result = svc.process_game_end("g1", "", "only")
        assert result is None

    def test_missing_loser_username(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        repo.create_user("only", "h", rating=1200)

        svc = RatingService(repository=repo)
        result = svc.process_game_end("g2", "only", "")
        assert result is None

    def test_winner_not_in_database(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        repo.create_user("exists", "h", rating=1200)

        svc = RatingService(repository=repo)
        result = svc.process_game_end("g3", "ghost", "exists")
        assert result is None

    def test_loser_not_in_database(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        repo.create_user("exists", "h", rating=1200)

        svc = RatingService(repository=repo)
        result = svc.process_game_end("g4", "exists", "ghost")
        assert result is None


# ─── Protocol message ─────────────────────────────────────────────────────────


class TestRatingUpdatedMessage:
    def test_message_format(self):
        msg = make_rating_updated("alice", 1200, 1216, 16)
        parsed = decode_message(msg)
        assert parsed["type"] == "rating_updated"
        assert parsed["payload"]["username"] == "alice"
        assert parsed["payload"]["old_rating"] == 1200
        assert parsed["payload"]["new_rating"] == 1216
        assert parsed["payload"]["change"] == 16

    def test_no_password_in_message(self):
        msg = make_rating_updated("alice", 1200, 1216, 16)
        assert "password" not in msg
        assert "hash" not in msg


# ─── Client state ─────────────────────────────────────────────────────────────


class TestClientRatingUpdate:
    def test_updates_own_rating(self):
        state = ClientGameState()
        state.apply_login_success("w", "alice", 1200)

        state.apply_rating_updated("alice", 1216)
        assert state.player_rating == 1216

    def test_ignores_opponent_rating(self):
        state = ClientGameState()
        state.apply_login_success("w", "alice", 1200)

        state.apply_rating_updated("bob", 1184)
        assert state.player_rating == 1200

    def test_processor_handles_rating_updated(self):
        state = ClientGameState()
        state.apply_login_success("b", "bob", 1200)

        gm = MagicMock(spec=GraphicsManager)
        gm.graphic_pieces = []
        gm.get_piece_at.return_value = None

        proc = ServerMessageProcessor(state, gm)
        proc.process_messages([{
            "type": "rating_updated",
            "payload": {
                "username": "bob",
                "old_rating": 1200,
                "new_rating": 1216,
                "change": 16,
            },
        }])

        assert state.player_rating == 1216

    def test_processor_ignores_other_player(self):
        state = ClientGameState()
        state.apply_login_success("w", "alice", 1200)

        gm = MagicMock(spec=GraphicsManager)
        gm.graphic_pieces = []
        gm.get_piece_at.return_value = None

        proc = ServerMessageProcessor(state, gm)
        proc.process_messages([{
            "type": "rating_updated",
            "payload": {
                "username": "bob",
                "old_rating": 1200,
                "new_rating": 1184,
                "change": -16,
            },
        }])

        assert state.player_rating == 1200


# ─── Atomic persistence ───────────────────────────────────────────────────────


class TestAtomicUpdateRatings:
    def test_both_updates_persisted(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        repo.create_user("alice", "h", rating=1200)
        repo.create_user("bob", "h", rating=1200)

        repo.update_ratings("alice", 1216, "bob", 1184)

        assert repo.get_user_by_username("alice").rating == 1216
        assert repo.get_user_by_username("bob").rating == 1184

    def test_missing_loser_rolls_back_winner(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        repo.create_user("alice", "h", rating=1200)
        # "ghost" does not exist

        with pytest.raises(ValueError):
            repo.update_ratings("alice", 1216, "ghost", 1184)

        # Alice's rating must NOT have changed
        assert repo.get_user_by_username("alice").rating == 1200

    def test_missing_winner_rolls_back_loser(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        repo.create_user("bob", "h", rating=1200)

        with pytest.raises(ValueError):
            repo.update_ratings("ghost", 1216, "bob", 1184)

        assert repo.get_user_by_username("bob").rating == 1200


class TestRatingServiceAtomicity:
    def test_failed_persistence_does_not_mark_processed(self):
        """If update_ratings raises, the game_id is not marked processed."""
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        repo.create_user("winner", "h", rating=1200)
        # Loser does not exist in DB — will cause failure

        svc = RatingService(repository=repo)

        # This should fail because "loser" is not in the DB
        # (get_user_by_username returns None → guard catches it before persistence)
        result = svc.process_game_end("game-fail", "winner", "loser_not_found")
        assert result is None

        # game_id NOT marked as processed — a retry with valid data can succeed
        repo.create_user("loser_not_found", "h", rating=1200)
        result2 = svc.process_game_end("game-fail", "winner", "loser_not_found")
        assert result2 is not None
        assert result2.winner.new_rating == 1216

    def test_failed_transaction_does_not_produce_result(self):
        """A persistence failure returns None (no messages should be sent)."""
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        # Only one user exists
        repo.create_user("only_one", "h", rating=1200)

        svc = RatingService(repository=repo)
        result = svc.process_game_end("game-x", "only_one", "missing")
        assert result is None

    def test_retry_succeeds_after_failure_resolved(self):
        """After fixing the failure condition, the same game_id can be retried."""
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        repo.create_user("alice", "h", rating=1200)

        svc = RatingService(repository=repo)

        # First attempt: bob missing
        result1 = svc.process_game_end("game-retry", "alice", "bob")
        assert result1 is None

        # Fix: create bob
        repo.create_user("bob", "h", rating=1200)

        # Retry: should succeed now
        result2 = svc.process_game_end("game-retry", "alice", "bob")
        assert result2 is not None
        assert repo.get_user_by_username("alice").rating == 1216
        assert repo.get_user_by_username("bob").rating == 1184


# ─── Game ID lifecycle ────────────────────────────────────────────────────────


class TestGameIdLifecycle:
    def test_same_event_twice_updates_only_once(self):
        """Duplicate GameEnded for the same game only updates ratings once."""
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        repo.create_user("p1", "h", rating=1200)
        repo.create_user("p2", "h", rating=1200)

        svc = RatingService(repository=repo)

        # First call — succeeds
        result1 = svc.process_game_end("game-A", "p1", "p2")
        assert result1 is not None

        # Second call with same game_id — skipped
        result2 = svc.process_game_end("game-A", "p1", "p2")
        assert result2 is None

        # Ratings only updated once
        assert repo.get_user_by_username("p1").rating == 1216
        assert repo.get_user_by_username("p2").rating == 1184

    def test_two_different_games_update_independently(self):
        """Two sequential games with different IDs both update ratings."""
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        repo.create_user("alice", "h", rating=1200)
        repo.create_user("bob", "h", rating=1200)

        svc = RatingService(repository=repo)

        # Game 1: alice wins
        result1 = svc.process_game_end("game-1", "alice", "bob")
        assert result1 is not None
        assert repo.get_user_by_username("alice").rating == 1216
        assert repo.get_user_by_username("bob").rating == 1184

        # Game 2: bob wins (ratings already changed from game 1)
        result2 = svc.process_game_end("game-2", "bob", "alice")
        assert result2 is not None

        # Bob was 1184, Alice was 1216. Bob wins the upset.
        alice_after = repo.get_user_by_username("alice")
        bob_after = repo.get_user_by_username("bob")

        # Both ratings changed again from their game-1 values
        assert bob_after.rating > 1184
        assert alice_after.rating < 1216

    def test_server_uses_engine_based_game_id(self):
        """Different GameSession engines produce different game IDs."""
        from game.server.game_session import GameSession
        from game.server.websocket_server import GameWebSocketServer

        repo = UserRepository(":memory:")
        repo.initialize_schema()
        rating_svc = RatingService(repository=repo)

        session1 = GameSession()
        session2 = GameSession()

        srv1 = GameWebSocketServer(session=session1, rating_service=rating_svc)
        srv2 = GameWebSocketServer(session=session2, rating_service=rating_svc)

        # Different sessions have different engine IDs
        assert srv1._game_id != srv2._game_id
