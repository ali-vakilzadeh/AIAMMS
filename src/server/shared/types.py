"""
Shared types and enums used across the CMMS server.

This module contains common type definitions that are used by multiple modules.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID


class Role(str, Enum):
    """User roles in the system."""
    SYS_ADMIN = "SYS_ADMIN"
    MANAGER = "MANAGER"
    REPORTER = "REPORTER"
    OPERATOR = "OPERATOR"
    MAINTENANCE = "MAINTENANCE"


class HealthStatus(str, Enum):
    """Module health status."""
    OK = "OK"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass
class RequestContext:
    """
    Request context passed to domain service functions.
    
    Built from verified JWT claims by API middleware.
    Every domain service function takes ctx as first param.
    """
    org_id: UUID | None
    user_id: UUID | None
    role: Role | None
    request_id: str
    timezone: str | None = None
    
    @classmethod
    def platform(cls, request_id: str) -> "RequestContext":
        """Create a platform-level context (no org/user)."""
        return cls(
            org_id=None,
            user_id=None,
            role=None,
            request_id=request_id,
        )


@dataclass
class Page:
    """Generic paginated response."""
    items: list[Any]
    page: int
    page_size: int
    total: int
    
    @property
    def total_pages(self) -> int:
        if self.page_size <= 0:
            return 0
        return (self.total + self.page_size - 1) // self.page_size
    
    @property
    def has_next(self) -> bool:
        return self.page * self.page_size < self.total
    
    @property
    def has_prev(self) -> bool:
        return self.page > 1


@dataclass
class ErrorResponse:
    """Standard HTTP error envelope."""
    error_code: str
    message: str
    details: dict = field(default_factory=dict)


# Common error codes
ERROR_CODES = {
    # Auth errors
    "UNAUTHORIZED": "Authentication required",
    "FORBIDDEN": "Access denied",
    "TOKEN_EXPIRED": "Access token has expired",
    "TOKEN_INVALID": "Invalid token format or signature",
    
    # Tenancy errors
    "TIER_LIMIT_REACHED": "Organization has reached its tier limit",
    "ORG_PAYMENT_OVERDUE": "Organization payment is overdue",
    
    # Not found
    "NOT_FOUND": "Resource not found",
    
    # Validation
    "VALIDATION_ERROR": "Request validation failed",
    "DUPLICATE_ENTRY": "Resource already exists",
    
    # State
    "INVALID_TRANSITION": "Invalid state transition",
    "RESOURCE_LOCKED": "Resource is locked by another operation",
}


class DomainError(Exception):
    """Base class for domain-specific exceptions."""
    def __init__(self, error_code: str, message: str, details: dict | None = None):
        self.error_code = error_code
        self.message = message
        self.details = details or {}
        super().__init__(message)
    
    def to_response(self) -> ErrorResponse:
        return ErrorResponse(
            error_code=self.error_code,
            message=self.message,
            details=self.details,
        )


class NotFoundError(DomainError):
    """Resource not found."""
    def __init__(self, resource: str, id: str | UUID):
        super().__init__(
            error_code="NOT_FOUND",
            message=f"{resource} with ID {id} not found",
            details={"resource": resource, "id": str(id)},
        )


class ForbiddenError(DomainError):
    """Access denied."""
    def __init__(self, action: str, resource: str | None = None):
        super().__init__(
            error_code="FORBIDDEN",
            message=f"Access denied for action '{action}'",
            details={"action": action, "resource": resource},
        )


class UnauthorizedError(DomainError):
    """Authentication required or failed."""
    def __init__(self, reason: str = "Authentication required"):
        super().__init__(
            error_code="UNAUTHORIZED",
            message=reason,
        )


class QuotaExceededError(DomainError):
    """Tier quota exceeded."""
    def __init__(self, resource: str, limit: int, current: int):
        super().__init__(
            error_code="TIER_LIMIT_REACHED",
            message=f"Cannot create more {resource}. Tier limit reached.",
            details={
                "resource": resource,
                "limit": limit,
                "current": current,
            },
        )


class InvalidTransitionError(DomainError):
    """Invalid state machine transition."""
    def __init__(self, entity: str, from_state: str, to_state: str):
        super().__init__(
            error_code="INVALID_TRANSITION",
            message=f"Cannot transition {entity} from '{from_state}' to '{to_state}'",
            details={
                "entity": entity,
                "from_state": from_state,
                "to_state": to_state,
            },
        )
