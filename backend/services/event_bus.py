"""
Event Bus — Lightweight in-process pub/sub for inter-pillar communication.

Events flow between the 4 pillars without tight coupling:
  Fetcher  →  RULES_UPDATED   →  Graph Builder
  Graph    →  GRAPH_CHANGED   →  Watchdog
  Watchdog →  GAP_DETECTED    →  Audit Engine
  Ingest   →  MANUAL_UPLOADED →  Audit Engine

Thread-safe, asyncio-compatible. No external dependencies.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """All system events."""
    RULES_UPDATED = "rules_updated"
    GRAPH_CHANGED = "graph_changed"
    MANUAL_UPLOADED = "manual_uploaded"
    GAP_DETECTED = "gap_detected"
    INGESTION_COMPLETE = "ingestion_complete"
    AUDIT_COMPLETE = "audit_complete"
    WATCHDOG_ALERT = "watchdog_alert"


@dataclass
class Event:
    """Immutable event payload."""
    event_type: EventType
    source: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    data: Dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"Event({self.event_type.value}, src={self.source}, keys={list(self.data.keys())})"


# Type alias for handlers
EventHandler = Callable[[Event], Coroutine[Any, Any, None]]


class EventBus:
    """
    In-process async event bus.

    Usage:
        bus = EventBus()

        async def on_rules(event: Event):
            print(f"Rules updated: {event.data}")

        bus.subscribe(EventType.RULES_UPDATED, on_rules)
        await bus.publish(Event(EventType.RULES_UPDATED, source="crawler", data={"count": 42}))
    """

    def __init__(self) -> None:
        self._handlers: Dict[EventType, List[EventHandler]] = {}
        self._history: List[Event] = []
        self._max_history: int = 100

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Register a handler for an event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        logger.debug(f"Subscribed {handler.__name__} to {event_type.value}")

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Remove a handler."""
        if event_type in self._handlers:
            self._handlers[event_type] = [
                h for h in self._handlers[event_type] if h is not handler
            ]

    async def publish(self, event: Event) -> None:
        """Publish an event to all subscribers. Non-blocking, fire-and-forget."""
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        handlers = self._handlers.get(event.event_type, [])
        if not handlers:
            logger.debug(f"No handlers for {event.event_type.value}")
            return

        logger.info(f"Publishing {event} to {len(handlers)} handler(s)")
        for handler in handlers:
            try:
                await handler(event)
            except Exception as e:
                logger.error(
                    f"Handler {handler.__name__} failed for {event.event_type.value}: {e}",
                    exc_info=True,
                )

    def publish_sync(self, event: Event) -> None:
        """Synchronous publish — creates event loop if needed."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.publish(event))
        except RuntimeError:
            asyncio.run(self.publish(event))

    def get_history(self, event_type: Optional[EventType] = None) -> List[Event]:
        """Returns recent event history, optionally filtered by type."""
        if event_type:
            return [e for e in self._history if e.event_type == event_type]
        return list(self._history)


# ──────────────────────────────────────────────────────────────────────────────
# Global singleton
# ──────────────────────────────────────────────────────────────────────────────

_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Returns the global EventBus singleton."""
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
