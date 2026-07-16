class PieceStateMachine:
    IDLE = "idle"
    MOVE = "move"
    JUMP = "jump"
    SHORT_REST = "short_rest"
    LONG_REST = "long_rest"

    ALLOWED_TRANSITIONS = {
        IDLE: {MOVE, JUMP, SHORT_REST, LONG_REST},

        MOVE: { SHORT_REST,LONG_REST, IDLE},

        JUMP: {IDLE, SHORT_REST},

        SHORT_REST: {IDLE, MOVE, JUMP, LONG_REST},

        LONG_REST: {IDLE, MOVE, JUMP},
    }

    def __init__(self, initial_state: str = IDLE):
        if initial_state not in self.ALLOWED_TRANSITIONS:
            raise ValueError(
                f"Unknown initial state: {initial_state}"
            )

        self._current_state = initial_state

    @property
    def current_state(self) -> str:
        return self._current_state

    def can_transition_to(self, new_state: str) -> bool:
        if new_state == self._current_state:
            return True

        if new_state not in self.ALLOWED_TRANSITIONS:
            return False

        return new_state in self.ALLOWED_TRANSITIONS[
            self._current_state
        ]

    def transition_to(self, new_state: str) -> bool:
        if new_state == self._current_state:
            return False

        if not self.can_transition_to(new_state):
            raise ValueError(
                f"Invalid state transition: "
                f"{self._current_state} -> {new_state}"
            )

        self._current_state = new_state
        return True

    def reset(self) -> None:
        self._current_state = self.IDLE