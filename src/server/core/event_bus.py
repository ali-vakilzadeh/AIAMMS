"""
Event Bus - Async event publishing with subscriber isolation.

Events are dot-delimited strings (e.g., 'cycle.due', 'user.registered').
Subscribers can use wildcard '*' to receive all events (used by AUDIT module).

Subscriber failures are isolated - one failing listener never breaks others or the publisher.
"""

import asyncio
from typing import Callable, Any
from dataclasses import dataclass, field
from datetime import datetime

from .utils import utcnow


@dataclass
class Subscription:
    """A single event subscription."""
    event: str
    handler: Callable[[dict], Any]  # async callable that takes payload dict
    post_commit: bool = False  # If True, deliver only after DB transaction commits


class EventBus:
    """
    Async event bus for publish/subscribe messaging.
    
    Features:
    - Subscriber isolation: failing listeners don't affect others
    - Post-commit delivery: optional deferred delivery for transactional integrity
    - Wildcard subscriptions: '*' receives all events
    - Duplicate prevention: same (event, handler) pair can't be registered twice
    
    Example:
        # Subscribe to cycle.due events
        core.subscribe('cycle.due', handle_cycle_due)
        
        # Subscribe to all events (AUDIT module)
        core.subscribe('*', handle_all_events)
        
        # Publish an event
        await core.publish('cycle.due', {'cycle_id': uuid, 'trigger_id': tid})
    """
    
    def __init__(self):
        # Map of event_name -> list[Subscription]
        self._subscribers: dict[str, list[Subscription]] = {}
        # Set of (event, handler) tuples for duplicate detection
        self._subscriptions_set: set[tuple[str, int]] = set()
        # Post-commit queue: list of (event, payload) to deliver after commit
        self._post_commit_queue: list[tuple[str, dict]] = []
    
    def subscribe(self, event: str, handler: Callable, post_commit: bool = False) -> None:
        """
        Register an event listener.
        
        Args:
            event: Event name (e.g., 'cycle.due') or '*' for wildcard
            handler: Async callable that takes payload dict
            post_commit: If True, deliver only after current DB transaction commits
        
        Raises:
            ValueError: If (event, handler) pair is already registered
        """
        handler_id = id(handler)
        sub_key = (event, handler_id)
        
        if sub_key in self._subscriptions_set:
            raise ValueError(f"Handler already subscribed to event '{event}'")
        
        self._subscriptions_set.add(sub_key)
        
        if event not in self._subscribers:
            self._subscribers[event] = []
        
        self._subscribers[event].append(
            Subscription(event=event, handler=handler, post_commit=post_commit)
        )
    
    async def publish(self, event: str, payload: dict, post_commit: bool = False) -> None:
        """
        Dispatch an event to all subscribers.
        
        Each subscriber runs in isolated try/except; a failing listener
        never breaks the publisher or other listeners.
        
        Args:
            event: Event name (dot-delimited, e.g., 'cycle.due')
            payload: JSON-serializable dict
            post_commit: If True, queue for delivery after DB commit instead of immediate
        
        Note:
            Wildcard subscribers ('*') receive ALL events.
        """
        if post_commit:
            self._post_commit_queue.append((event, payload))
            return
        
        await self._dispatch(event, payload)
    
    async def _dispatch(self, event: str, payload: dict) -> None:
        """
        Internal dispatch to all matching subscribers.
        
        Collects all errors but doesn't raise them - just logs.
        """
        import logging
        logger = logging.getLogger("core.event_bus")
        
        # Get direct subscribers and wildcard subscribers
        direct_subs = self._subscribers.get(event, [])
        wildcard_subs = self._subscribers.get('*', [])
        
        all_subs = direct_subs + wildcard_subs
        
        if not all_subs:
            return
        
        # Fire all handlers concurrently but isolate failures
        tasks = []
        for sub in all_subs:
            tasks.append(self._call_handler(sub.handler, event, payload))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Log any failures without breaking flow
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                handler_name = getattr(all_subs[i].handler, '__name__', 'unknown')
                logger.error(
                    f"Event handler '{handler_name}' for event '{event}' failed: {result}",
                    exc_info=result
                )
    
    async def _call_handler(
        self,
        handler: Callable,
        event: str,
        payload: dict
    ) -> None:
        """Call a single handler with isolation."""
        try:
            if asyncio.iscoroutinefunction(handler):
                await handler(payload)
            else:
                handler(payload)
        except Exception as e:
            # Re-raise so gather catches it
            raise e
    
    async def flush_post_commit(self) -> None:
        """
        Flush the post-commit queue.
        
        Called by DB module after successful transaction commit.
        Delivers all queued events and clears the queue.
        """
        queue = self._post_commit_queue.copy()
        self._post_commit_queue.clear()
        
        for event, payload in queue:
            await self._dispatch(event, payload)
    
    def clear_post_commit_queue(self) -> None:
        """
        Clear the post-commit queue without delivering.
        
        Called by DB module after transaction rollback.
        """
        self._post_commit_queue.clear()
    
    def get_subscriber_count(self, event: str) -> int:
        """Get number of subscribers for an event (including wildcards)."""
        direct = len(self._subscribers.get(event, []))
        wildcard = len(self._subscribers.get('*', []))
        return direct + wildcard
    
    def list_events(self) -> list[str]:
        """Return list of all event names with subscribers (excluding wildcard)."""
        return [k for k in self._subscribers.keys() if k != '*']
    
    def clear(self) -> None:
        """Clear all subscriptions. Used for testing."""
        self._subscribers.clear()
        self._subscriptions_set.clear()
        self._post_commit_queue.clear()


# Global event bus instance (lazy-initialized by core)
_event_bus_instance: EventBus | None = None


def get_event_bus() -> EventBus:
    """Get the global event bus instance."""
    global _event_bus_instance
    if _event_bus_instance is None:
        _event_bus_instance = EventBus()
    return _event_bus_instance
