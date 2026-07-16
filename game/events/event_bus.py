"""
Lightweight publish/subscribe event bus.

Subscribers register for a specific event type. When an event of that type
is published, all registered handlers are called synchronously in
registration order.
"""

from typing import Any, Callable


class EventBus:
    """Simple synchronous event bus for decoupled communication."""

    def __init__(self):
        self._listeners: dict[type, list[Callable]] = {}

    def subscribe(self, event_type: type, handler: Callable) -> None:
        """Register a handler for a specific event type."""
        self._listeners.setdefault(event_type, []).append(handler)

    def publish(self, event: Any) -> None:
        """Publish an event to all registered handlers of its type."""
        for handler in self._listeners.get(type(event), []):
            handler(event)
