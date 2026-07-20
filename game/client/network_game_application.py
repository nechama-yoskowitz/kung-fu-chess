"""
Network-mode graphical application composition root.

Connects to a remote server and renders the game based on server messages.
"""

import logging
import queue
import time

from game.client.client_game_state import ClientGameState
from game.client.network_game_gateway import NetworkGameGateway
from game.client.network_transport import NetworkTransport
from game.client.server_message_processor import ServerMessageProcessor
from game.controller.controller import Controller
from game.events import EventBus
from game.graphics.frame_composer import FrameComposer
from game.graphics.game_end_animation import GameEndAnimation
from game.graphics.game_loop import GameLoop
from game.graphics.game_screen_composer import GameScreenComposer
from game.graphics.graphics_manager import GraphicsManager
from game.graphics.mouse_input_adapter import MouseInputAdapter
from game.graphics.renderer import Renderer
from game.graphics.sprites.sprite_manager import SpriteManager
from game.history.move_history_observer import MoveHistoryObserver
from game.model.board_mapper import BoardMapper
from game.sound.sound_observer import SoundObserver
from game.sound.sound_player import SoundPlayer

logger = logging.getLogger(__name__)

BOARD_IMAGE_PATH = "game/graphics/assets/board.png"
PIECES_ROOT_PATH = "game/graphics/assets/pieces"
SOUNDS_ROOT_PATH = "game/graphics/assets/sounds"
PIECE_SCALE = 0.70
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 800


class NetworkGameApplication:
    """
    Composition root for network multiplayer mode.

    Connects to a server, receives authoritative state, renders the game.
    """

    def __init__(self, server_uri: str, username: str = "Player",
                 password: str = "", action: str = "login"):
        self._server_uri = server_uri
        self._username = username
        self._password = password
        self._action = action
        self._running = True

        # Client-side event bus for sound/animation observers
        self.event_bus = EventBus()

        # State
        self.state = ClientGameState()

        # Network queues
        self._outgoing = queue.Queue()
        self._incoming = queue.Queue()

        # Transport
        self.transport = NetworkTransport(server_uri, self._outgoing, self._incoming)

        # Graphics
        self.renderer = Renderer(BOARD_IMAGE_PATH)
        self.sprite_manager = SpriteManager(PIECES_ROOT_PATH)

        rows, cols = 8, 8
        cell_width, cell_height = self.renderer.get_cell_size(rows, cols)
        piece_size = (int(cell_width * PIECE_SCALE), int(cell_height * PIECE_SCALE))

        self.graphics_manager = GraphicsManager(
            sprite_manager=self.sprite_manager,
            piece_size=piece_size,
        )

        # Message processor
        self.processor = ServerMessageProcessor(
            state=self.state,
            graphics_manager=self.graphics_manager,
            event_bus=self.event_bus,
            on_shutdown=self._request_shutdown,
        )

        # Gateway + Controller
        self.gateway = NetworkGameGateway(self.state, self._outgoing)
        self.controller = Controller(
            gateway=self.gateway,
            board_mapper=BoardMapper(cell_width=cell_width, cell_height=cell_height),
        )

        # Animations
        self.game_end_animation = GameEndAnimation(event_bus=self.event_bus)

        # Sound
        self.sound_player = SoundPlayer(SOUNDS_ROOT_PATH)
        self.sound_observer = SoundObserver(
            event_bus=self.event_bus,
            sound_player=self.sound_player,
        )

        # Move history
        self.move_history = MoveHistoryObserver(
            event_bus=self.event_bus,
            clock_provider=lambda: self.state.clock,
        )

        # Frame composition
        self.frame_composer = FrameComposer(
            renderer=self.renderer,
            graphics_manager=self.graphics_manager,
            rows=rows,
            cols=cols,
            cooldown_provider=lambda: self.state.get_cooldown_indicators(),
            selection_provider=lambda: self.controller.selected,
            game_end_animation=self.game_end_animation,
        )

        self.screen_composer = GameScreenComposer(
            frame_composer=self.frame_composer,
            window_width=WINDOW_WIDTH,
            window_height=WINDOW_HEIGHT,
            white_score_provider=lambda: self.state.white_score,
            black_score_provider=lambda: self.state.black_score,
            white_moves_provider=lambda: self.move_history.white_moves,
            black_moves_provider=lambda: self.move_history.black_moves,
            player_identity_provider=lambda: self.state.player_identity_text,
        )

        self.mouse_input_adapter = MouseInputAdapter(
            self.controller,
            game_over_provider=lambda: self.state.game_over,
            board_rect_provider=self._get_board_rect,
            original_board_size_provider=self._get_original_board_size,
            input_blocked_provider=lambda: not self.state.connected,
        )

    def run(self):
        """Connect to server and run the graphical game loop."""
        self.transport.start()

        # Send login request as the first outgoing message
        from game.server.protocol import make_login_request
        self._outgoing.put_nowait(
            make_login_request(self._username, self._password, self._action)
        )
        # Clear password from instance immediately after queuing
        self._password = None

        # Wait briefly for initial connection
        deadline = time.monotonic() + 5.0
        while not self.state.connected and time.monotonic() < deadline:
            messages = self.transport.drain_incoming()
            self.processor.process_messages(messages)
            time.sleep(0.05)

        if not self.state.connected:
            error = self.transport.error or "Connection timeout"
            print(f"Failed to connect: {error}")
            self.transport.stop()
            return

        # Print friendly shell confirmation
        if self.state.player_identity_text:
            color_name = "White" if self.state.player_color == "w" else "Black"
            print(f"Logged in as '{self.state.player_username}' - you are {color_name}.")

        game_loop = GameLoop(
            frame_composer=self.frame_composer,
            graphics_manager=self.graphics_manager,
            mouse_input_adapter=self.mouse_input_adapter,
            screen_composer=self.screen_composer,
            game_end_animation=self.game_end_animation,
            engine_updater=self._network_update,
            target_fps=60,
        )

        try:
            game_loop.run()
        finally:
            self.transport.stop(timeout=2.0)

    def _network_update(self, delta_ms: float) -> None:
        """Drain incoming messages each frame (called by GameLoop as engine_updater)."""
        if not self._running:
            return
        self.state.advance_clock(delta_ms)
        messages = self.transport.drain_incoming()
        if messages:
            self.processor.process_messages(messages)

    def _request_shutdown(self) -> None:
        """Called by the message processor on game_full or fatal error."""
        self._running = False
        self.transport.stop(timeout=1.0)

    def _get_board_rect(self):
        m = self.screen_composer.metrics
        return (m.board_left, m.board_top, m.board_size, m.board_size)

    def _get_original_board_size(self):
        h, w = self.renderer.board_template.img.shape[:2]
        return (w, h)
