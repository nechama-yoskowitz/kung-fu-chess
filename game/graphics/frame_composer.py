"""
Composes a complete rendered frame each tick.

Rendering order:
1. Board background (start_frame)
2. Cooldown overlays
3. Pieces
4. Selection highlight
5. Game-over overlay + text
"""

from game.graphics.graphics_manager import GraphicsManager
from game.graphics.renderer import Renderer


class FrameComposer:
    """
    Responsible for assembling one rendered frame per tick.

    Knows the rendering order and which overlays to draw, but does not
    own game state or make game decisions.
    """

    def __init__(
        self,
        renderer: Renderer,
        graphics_manager: GraphicsManager,
        rows: int,
        cols: int,
        cooldown_provider=None,
        selection_provider=None,
        game_over_provider=None,
    ):
        self.renderer = renderer
        self.graphics_manager = graphics_manager
        self.rows = rows
        self.cols = cols
        self.cooldown_provider = cooldown_provider
        self.selection_provider = selection_provider
        self.game_over_provider = game_over_provider

    def compose(self):
        """Render one complete frame and return the canvas."""
        canvas = self.renderer.start_frame()

        # Cooldown overlays drawn before pieces so pieces remain visible.
        if self.cooldown_provider:
            for cd_row, cd_col, progress in self.cooldown_provider():
                self.renderer.draw_cooldown_indicator(
                    row=cd_row, col=cd_col, progress=progress,
                    rows=self.rows, cols=self.cols,
                )

        self.graphics_manager.draw(
            renderer=self.renderer,
            rows=self.rows,
            cols=self.cols,
        )

        if self.selection_provider:
            selected = self.selection_provider()
            if selected is not None:
                self.renderer.draw_cell_highlight(
                    row=selected[0], col=selected[1],
                    rows=self.rows, cols=self.cols,
                )

        if self.game_over_provider and self.game_over_provider():
            self.renderer.draw_game_over_overlay()
            self.renderer.draw_centered_text("GAME OVER")

        return canvas
