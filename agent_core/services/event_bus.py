import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, List

logger = logging.getLogger("agent_core.event_bus")

EventHandler = Callable[[str, Dict[str, Any]], Coroutine[Any, Any, None]]

class EventBus:
    """A simple asynchronous local event bus for inter-service communication.

    This acts as the foundation for decoupling the sequential pipeline in the Orchestrator.
    Services emit events (e.g., 'PROFILE_ANALYZED') and other services can subscribe to them
    to react autonomously.
    """
    def __init__(self):
        self._subscribers: Dict[str, List[EventHandler]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Subscribe an async handler to a specific event type."""
        async with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(handler)
            logger.debug(f"Subscribed handler {handler.__name__} to event {event_type}")

    async def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """Unsubscribe a handler from a specific event type."""
        async with self._lock:
            if event_type in self._subscribers:
                try:
                    self._subscribers[event_type].remove(handler)
                    logger.debug(f"Unsubscribed handler {handler.__name__} from event {event_type}")
                except ValueError:
                    pass

    async def emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Emit an event. All registered handlers will be executed concurrently."""
        handlers = []
        async with self._lock:
            handlers = self._subscribers.get(event_type, []).copy()

        if not handlers:
            logger.debug(f"Event emitted with no subscribers: {event_type}")
            return

        logger.info(f"Emitting event: {event_type} to {len(handlers)} handlers.")

        # Execute handlers concurrently, catching errors so one failing handler doesn't stop others
        async def safe_execute(h: EventHandler):
            try:
                await h(event_type, payload)
            except Exception as e:
                logger.error(f"Error executing event handler {h.__name__} for {event_type}: {e}", exc_info=True)

        tasks = [asyncio.create_task(safe_execute(h)) for h in handlers]
        await asyncio.gather(*tasks)

# Global singleton event bus
_event_bus = EventBus()

def get_event_bus() -> EventBus:
    return _event_bus
