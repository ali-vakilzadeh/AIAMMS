"""
Shared module - Common types and events used across CMMS server.
"""

from .types import (
    Role,
    HealthStatus,
    RequestContext,
    Page,
    ErrorResponse,
    DomainError,
    NotFoundError,
    ForbiddenError,
    UnauthorizedError,
    QuotaExceededError,
    InvalidTransitionError,
    ERROR_CODES,
)

from .events_catalog import (
    Events,
    EVENT_METADATA,
    get_event_consumers,
    get_event_description,
)

__all__ = [
    # Types
    "Role",
    "HealthStatus",
    "RequestContext",
    "Page",
    "ErrorResponse",
    "DomainError",
    "NotFoundError",
    "ForbiddenError",
    "UnauthorizedError",
    "QuotaExceededError",
    "InvalidTransitionError",
    "ERROR_CODES",
    # Events
    "Events",
    "EVENT_METADATA",
    "get_event_consumers",
    "get_event_description",
]
