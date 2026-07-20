"""
Rating system for Kung-Fu Chess.

Provides ELO calculation and rating update coordination.
"""

from game.server.rating.elo_calculator import EloCalculator

__all__ = ["EloCalculator"]
