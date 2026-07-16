"""
Legacy entry point — delegates to run_game.py.

Use run_game.py directly as the application launcher.
"""

from run_game import GameApplication

if __name__ == "__main__":
    app = GameApplication()
    app.run()
