"""Kung-Fu Chess — application entry point."""

from game.application.game_application import GameApplication

if __name__ == "__main__":
    app = GameApplication()
    app.run()
