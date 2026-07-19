"""
Composes a complete rendered frame each tick.

Rendering order:
1. Board background (start_frame)
2. Cooldown overlays
3. Pieces
4. Selection highlight
5. Game-over overlay + text (driven by GameEndAnimation state)
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
        game_end_animation=None,
        game_start_animation=None,
    ):
        self.renderer = renderer
        self.graphics_manager = graphics_manager
        self.rows = rows
        self.cols = cols
        self.cooldown_provider = cooldown_provider
        self.selection_provider = selection_provider
        self.game_end_animation = game_end_animation
        self.game_start_animation = game_start_animation

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

        # Game-start countdown overlay
        if self.game_start_animation and self.game_start_animation.active:
            text = self.game_start_animation.current_text
            if text:
                self.renderer.draw_game_over_overlay(alpha=0.4)
                self.renderer.draw_start_countdown(text)

        # Game-end overlay with animated fade-in
        if self.game_end_animation and self.game_end_animation.active:
            anim = self.game_end_animation
            if anim.opacity > 0:
                self.renderer.draw_game_over_overlay(alpha=anim.opacity)
            if anim.text_opacity > 0:
                text_color = (255, 255, 255)
                self.renderer.draw_centered_text(
                    "GAME OVER", font_size=2.0,
                    color=text_color, thickness=3,
                )
                winner_text = anim.winner_text
                if winner_text:
                    self.renderer.draw_centered_text_offset(
                        winner_text, y_offset=60, font_size=1.2,
                        color=text_color, thickness=2,
                    )

        return canvas
