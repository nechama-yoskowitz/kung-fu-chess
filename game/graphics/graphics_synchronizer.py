from game.graphics.graphics_manager import GraphicsManager


class GraphicsSynchronizer:
    """
    One-way synchronization layer: reads board state from the game engine
    and initializes the graphics layer accordingly.

    This class lives in the graphics layer and depends on the engine's
    public board attribute. The engine has no knowledge of this class
    or any graphics types.

    Current scope:
    - Initial board setup (pieces placed at their starting positions).

    Future scope (not yet implemented):
    - Movement, captures, jumps, cooldown visualization.
    """

    def __init__(self, graphics_manager: GraphicsManager):
        self.graphics_manager = graphics_manager

    def initialize(self, board) -> None:
        """
        Read the current board state and populate the graphics layer.

        Parameters
        ----------
        board : list[list[str]]
            The engine's board matrix. Each cell is either a piece token
            (e.g. "wQ", "bK") or "." for empty.
        """
        self.graphics_manager.initialize_from_board(board)
