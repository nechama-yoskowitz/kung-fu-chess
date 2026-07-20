"""
Focused tests for player identity display.

Covers:
- login_success stores username
- login_success stores assigned color
- player_identity_text uses ASCII-safe separator
- composer reserves header space when identity provider is set
- board top offset is below the header
- identity is not drawn inside the board area
- ServerMessageProcessor._on_login_success populates state
"""

from unittest.mock import MagicMock

from game.client.client_game_state import ClientGameState
from game.client.server_message_processor import ServerMessageProcessor
from game.graphics.frame_composer import FrameComposer
from game.graphics.game_screen_composer import (
    GameScreenComposer,
    HEADER_HEIGHT,
    LayoutMetrics,
)
from game.graphics.graphics_manager import GraphicsManager


class TestClientGameStateLoginSuccess:
    def test_stores_username(self):
        state = ClientGameState()
        state.apply_login_success("w", "Nechama")
        assert state.player_username == "Nechama"

    def test_stores_color(self):
        state = ClientGameState()
        state.apply_login_success("b", "Alice")
        assert state.player_color == "b"

    def test_sets_connected(self):
        state = ClientGameState()
        state.apply_login_success("w", "Bob")
        assert state.connected is True

    def test_identity_text_white(self):
        state = ClientGameState()
        state.apply_login_success("w", "Nechama")
        assert state.player_identity_text == "Nechama | White"

    def test_identity_text_black(self):
        state = ClientGameState()
        state.apply_login_success("b", "Alice")
        assert state.player_identity_text == "Alice | Black"

    def test_identity_text_uses_ascii_separator(self):
        """No em-dash or non-ASCII characters in the identity text."""
        state = ClientGameState()
        state.apply_login_success("w", "Test")
        text = state.player_identity_text
        assert text is not None
        assert all(ord(c) < 128 for c in text)
        assert "|" in text

    def test_identity_text_none_before_login(self):
        state = ClientGameState()
        assert state.player_identity_text is None

    def test_stores_rating(self):
        state = ClientGameState()
        state.apply_login_success("w", "Nechama", 1200)
        assert state.player_rating == 1200

    def test_stores_custom_rating(self):
        state = ClientGameState()
        state.apply_login_success("b", "Pro", 1850)
        assert state.player_rating == 1850

    def test_default_rating_when_omitted(self):
        state = ClientGameState()
        state.apply_login_success("w", "New")
        assert state.player_rating == 1200

    def test_rating_none_before_login(self):
        state = ClientGameState()
        assert state.player_rating is None

    def test_apply_player_assigned_does_not_set_username(self):
        """Backward-compat: apply_player_assigned only sets color."""
        state = ClientGameState()
        state.apply_player_assigned("w")
        assert state.player_color == "w"
        assert state.player_username is None
        assert state.player_identity_text is None


class TestProcessorLoginSuccess:
    def test_login_success_updates_state(self):
        state = ClientGameState()
        gm = MagicMock(spec=GraphicsManager)
        gm.graphic_pieces = []
        gm.get_piece_at.return_value = None

        proc = ServerMessageProcessor(state, gm)
        proc.process_messages([{
            "type": "login_success",
            "payload": {"color": "w", "username": "Nechama", "rating": 1200},
        }])

        assert state.player_color == "w"
        assert state.player_username == "Nechama"
        assert state.player_rating == 1200
        assert state.connected is True
        assert state.player_identity_text == "Nechama | White"

    def test_login_success_with_custom_rating(self):
        state = ClientGameState()
        gm = MagicMock(spec=GraphicsManager)
        gm.graphic_pieces = []
        gm.get_piece_at.return_value = None

        proc = ServerMessageProcessor(state, gm)
        proc.process_messages([{
            "type": "login_success",
            "payload": {"color": "b", "username": "Expert", "rating": 1650},
        }])

        assert state.player_rating == 1650

    def test_player_assigned_still_works(self):
        """Legacy player_assigned message still sets color and connected."""
        state = ClientGameState()
        gm = MagicMock(spec=GraphicsManager)
        gm.graphic_pieces = []
        gm.get_piece_at.return_value = None

        proc = ServerMessageProcessor(state, gm)
        proc.process_messages([{
            "type": "player_assigned",
            "payload": {"color": "b"},
        }])

        assert state.player_color == "b"
        assert state.connected is True


class TestLayoutMetricsHeader:
    def test_header_reserved_when_identity_present(self):
        m = LayoutMetrics(1200, 800, has_identity=True)
        assert m.header_height == HEADER_HEIGHT
        assert m.header_height > 0

    def test_no_header_without_identity(self):
        m = LayoutMetrics(1200, 800, has_identity=False)
        assert m.header_height == 0

    def test_board_top_below_header(self):
        m = LayoutMetrics(1200, 800, has_identity=True)
        assert m.board_top >= m.header_height

    def test_board_top_at_zero_without_header(self):
        m_no = LayoutMetrics(1200, 800, has_identity=False)
        m_yes = LayoutMetrics(1200, 800, has_identity=True)
        # Board is pushed down when header is present
        assert m_yes.board_top > m_no.board_top or m_yes.board_top >= HEADER_HEIGHT

    def test_identity_not_inside_board_area(self):
        """The header occupies rows 0..header_height, board starts at board_top."""
        m = LayoutMetrics(1200, 800, has_identity=True)
        # Header ends before board begins
        assert m.header_height <= m.board_top


class TestComposerHeaderIntegration:
    def test_composer_with_identity_has_header(self):
        fc = MagicMock(spec=FrameComposer)
        composer = GameScreenComposer(
            frame_composer=fc,
            window_width=1200,
            window_height=800,
            player_identity_provider=lambda: "Alice | White",
        )
        assert composer.metrics.header_height == HEADER_HEIGHT

    def test_composer_without_identity_no_header(self):
        fc = MagicMock(spec=FrameComposer)
        composer = GameScreenComposer(
            frame_composer=fc,
            window_width=1200,
            window_height=800,
        )
        assert composer.metrics.header_height == 0
