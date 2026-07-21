"""
Rating update coordinator.

Reacts to game completion, computes new ELO ratings, persists them,
and produces the data that should be sent to clients.

Does not know about WebSockets or protocol serialization.
"""

import logging
from dataclasses import dataclass

from game.server.auth.user_repository import UserRepository
from game.server.rating.elo_calculator import EloCalculator

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RatingUpdate:
    """Result of a rating update for one player."""

    username: str
    old_rating: int
    new_rating: int
    change: int


@dataclass(frozen=True)
class GameRatingResult:
    """Result of processing a game-end for rating purposes."""

    winner: RatingUpdate
    loser: RatingUpdate


class RatingService:
    """
    Coordinates ELO updates after a game ends.

    Responsibilities:
    - Look up current ratings from the repository.
    - Delegate calculation to EloCalculator.
    - Persist updated ratings.
    - Return structured results for protocol messaging.

    Guards against duplicate processing via a set of processed game IDs.
    """

    def __init__(
        self,
        repository: UserRepository,
        calculator: EloCalculator | None = None,
    ):
        self._repo = repository
        self._calc = calculator or EloCalculator(k_factor=32)
        self._processed_games: set[str] = set()

    def process_game_end(
        self,
        game_id: str,
        winner_username: str,
        loser_username: str,
    ) -> GameRatingResult | None:
        """
        Process a completed game and update both players' ratings.

        Parameters
        ----------
        game_id : str
            Unique identifier for this game instance (prevents duplicates).
        winner_username : str
            Username of the winning player.
        loser_username : str
            Username of the losing player.

        Returns
        -------
        GameRatingResult | None
            The rating changes for both players, or None if the update
            was skipped (duplicate game_id, missing user, etc.).
        """
        # Guard: no duplicate processing
        if game_id in self._processed_games:
            logger.warning(f"Duplicate game_id skipped: {game_id}")
            return None

        # Guard: both usernames must be non-empty
        if not winner_username or not loser_username:
            logger.warning("Rating update skipped: missing username")
            return None

        # Look up current ratings
        winner_record = self._repo.get_user_by_username(winner_username)
        loser_record = self._repo.get_user_by_username(loser_username)

        if winner_record is None or loser_record is None:
            logger.warning("Rating update skipped: user not found in database")
            return None

        old_winner_rating = winner_record.rating
        old_loser_rating = loser_record.rating

        # Calculate new ratings
        new_winner_rating, new_loser_rating = self._calc.calculate(
            old_winner_rating, old_loser_rating
        )

        # Persist atomically — only mark as processed after success
        self._repo.update_ratings(
            winner_username, new_winner_rating,
            loser_username, new_loser_rating,
        )
        self._processed_games.add(game_id)

        logger.info(
            f"Rating updated: {winner_username} {old_winner_rating}->{new_winner_rating}, "
            f"{loser_username} {old_loser_rating}->{new_loser_rating}"
        )

        return GameRatingResult(
            winner=RatingUpdate(
                username=winner_username,
                old_rating=old_winner_rating,
                new_rating=new_winner_rating,
                change=new_winner_rating - old_winner_rating,
            ),
            loser=RatingUpdate(
                username=loser_username,
                old_rating=old_loser_rating,
                new_rating=new_loser_rating,
                change=new_loser_rating - old_loser_rating,
            ),
        )
