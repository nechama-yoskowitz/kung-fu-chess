"""
Pure ELO rating calculation.

Contains only math. Does not know about WebSockets, SQLite, sessions,
the game engine, or protocol messages.
"""


class EloCalculator:
    """
    Standard ELO rating calculator.

    Uses the expected-score formula with a configurable K-factor.
    Winner scores 1, loser scores 0.
    """

    def __init__(self, k_factor: int = 32):
        if k_factor <= 0:
            raise ValueError("k_factor must be positive")
        self._k = k_factor

    @property
    def k_factor(self) -> int:
        return self._k

    def calculate(
        self,
        winner_rating: int,
        loser_rating: int,
    ) -> tuple[int, int]:
        """
        Calculate new ratings after a game.

        Parameters
        ----------
        winner_rating : int
            Current rating of the winning player.
        loser_rating : int
            Current rating of the losing player.

        Returns
        -------
        (new_winner_rating, new_loser_rating) : tuple[int, int]
            Updated ratings rounded to the nearest integer.
        """
        expected_winner = self._expected_score(winner_rating, loser_rating)
        expected_loser = self._expected_score(loser_rating, winner_rating)

        new_winner = winner_rating + self._k * (1.0 - expected_winner)
        new_loser = loser_rating + self._k * (0.0 - expected_loser)

        return round(new_winner), round(new_loser)

    @staticmethod
    def _expected_score(rating_a: int, rating_b: int) -> float:
        """Compute the expected score for player A against player B."""
        return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))
