from game.model.board_mapper import BoardMapper
from game.model.board import is_inside_board
from game.model.pieces import same_color, is_empty, get_color


class Controller:
    """
    Translate user input into game requests.

    The controller is responsible for:
    - remembering the selected cell,
    - interpreting the first and second clicks,
    - forwarding move and jump requests through a gateway.

    The gateway abstracts whether commands go to a local engine or a remote server.
    Pixel-to-cell conversion is delegated to BoardMapper.
    The controller does not validate chess rules
    and does not modify the board directly.
    """

    def __init__(self, gateway=None, board_mapper=None, *, engine=None):
        """
        Parameters
        ----------
        gateway : GameCommandGateway
            The command gateway (preferred).
        engine : GameEngine
            Legacy parameter — if provided without gateway, wraps it
            in a LocalGameGateway for backward compatibility.
        board_mapper : BoardMapper
            Pixel-to-cell converter.
        """
        if gateway is not None:
            # If a raw engine-like object was passed as gateway (legacy positional
            # usage), detect it by the absence of player_color and wrap it.
            if not hasattr(gateway, 'player_color'):
                from game.controller.local_game_gateway import LocalGameGateway
                self._gateway = LocalGameGateway(gateway)
            else:
                self._gateway = gateway
        elif engine is not None:
            from game.controller.local_game_gateway import LocalGameGateway
            self._gateway = LocalGameGateway(engine)
        else:
            raise ValueError("Controller requires either gateway or engine")

        self._selected = None
        self.board_mapper = board_mapper or BoardMapper()

    @property
    def selected(self):
        """
        The currently selected cell, or None.

        Automatically clears if the selected cell has become empty
        or no longer contains an own piece (e.g. the piece moved away
        due to a server-resolved move, or was captured).
        """
        if self._selected is not None:
            row, col = self._selected
            board = self._gateway.board
            if row < len(board) and col < len(board[0]):
                piece = board[row][col]
                if is_empty(piece) or not self._is_own_piece(piece):
                    self._selected = None
            else:
                self._selected = None
        return self._selected

    @selected.setter
    def selected(self, value):
        self._selected = value

    @property
    def board(self):
        """Read-only access to the board for selection logic."""
        return self._gateway.board

    def click(self, x, y):
        """
        Process a click at pixel coordinates.

        The first valid click selects a piece.
        The second click requests a move through the gateway.

        Returns True if a move was accepted,
        otherwise returns False.
        """
        row, col = self.board_mapper.pixel_to_cell(x, y)

        if not is_inside_board(
            self._gateway.board,
            row,
            col,
        ):
            if self.selected is not None:
                self.selected = None

            return False

        clicked_piece = self._gateway.board[row][col]

        # First click: select a non-moving, non-resting piece.
        if self.selected is None:
            if (
                not is_empty(clicked_piece)
                and not self._gateway.is_piece_moving_at(row, col)
                and not self._gateway.is_piece_resting_at(row, col)
                and self._is_own_piece(clicked_piece)
            ):
                self.selected = (row, col)

            return False

        selected_row, selected_col = self.selected
        selected_piece = self._gateway.board[selected_row][selected_col]

        # Clicking another friendly piece switches the selection.
        if (
            not is_empty(clicked_piece)
            and same_color(selected_piece, clicked_piece)
        ):
            if (
                not self._gateway.is_piece_moving_at(row, col)
                and not self._gateway.is_piece_resting_at(row, col)
            ):
                self.selected = (row, col)

            return False

        # Every second click inside the board completes the selection attempt.
        self.selected = None

        result = self._gateway.request_move(
            selected_row,
            selected_col,
            row,
            col,
        )

        return result.is_accepted

    def jump(self, x, y):
        """
        Process a jump command at pixel coordinates.

        Returns True if the jump was accepted,
        otherwise returns False.
        """
        row, col = self.board_mapper.pixel_to_cell(x, y)

        if not is_inside_board(
            self._gateway.board,
            row,
            col,
        ):
            return False

        return self._gateway.request_jump(row, col)

    def _is_own_piece(self, piece: str) -> bool:
        """
        Check if the piece belongs to this player.

        If gateway.player_color is None (local mode), all pieces are selectable.
        In network mode, only pieces matching the assigned color can be selected.
        """
        color = self._gateway.player_color
        if color is None:
            return True
        return get_color(piece) == color
