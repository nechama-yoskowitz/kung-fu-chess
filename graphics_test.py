"""Legacy entry point — delegates to run_game.py."""

from game.application.game_application import GameApplication

if __name__ == "__main__":
    app = GameApplication()
    app.run()
