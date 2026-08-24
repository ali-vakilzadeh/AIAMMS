"""
Utility functions for the core module.

Provides:
- utcnow(): Timezone-aware UTC datetime (never use datetime.now directly)
- new_id(): UUID4 generator
- new_request_id(): Short unique string for request correlation
"""

import uuid
import secrets
from datetime import datetime, timezone


def utcnow() -> datetime:
    """
    Get current UTC datetime with timezone info.
    
    This is the ONLY clock source modules should use.
    Never call datetime.now() directly - always use this function.
    
    Returns:
        datetime: Current UTC time with tzinfo=timezone.utc
    
    Example:
        ts = core.utcnow()
        # Use for all timestamps in business logic
    """
    return datetime.now(timezone.utc)


def new_id() -> uuid.UUID:
    """
    Generate a new UUID v4.
    
    This is the standard ID generator for all business records.
    
    Returns:
        UUID: A new random UUID v4
    
    Example:
        user_id = core.new_id()
        org_id = core.new_id()
    """
    return uuid.uuid4()


def new_request_id() -> str:
    """
    Generate a short unique request ID for correlation.
    
    Uses secrets.token_hex(8) for 16-character hex string.
    Suitable for logging correlation and distributed tracing.
    
    Returns:
        str: 16-character hex string
    
    Example:
        request_id = core.new_request_id()
        # Include in all log entries for this request
    """
    return secrets.token_hex(8)


def short_id() -> str:
    """
    Generate a shorter unique ID (8 chars).
    
    Useful for codes, tokens where full UUID is too long.
    Not cryptographically secure - use secrets.token_hex() directly for tokens.
    
    Returns:
        str: 8-character hex string
    """
    return secrets.token_hex(4)


def mask_value(value: str, visible_chars: int = 4) -> str:
    """
    Mask a sensitive value for logging.
    
    Shows only the last N characters, masks the rest with asterisks.
    
    Args:
        value: The string to mask
        visible_chars: Number of characters to show at end (default 4)
    
    Returns:
        str: Masked string
    
    Example:
        mask_value("secret_api_key_12345") -> "**************12345"
    """
    if len(value) <= visible_chars:
        return "*" * len(value)
    return "*" * (len(value) - visible_chars) + value[-visible_chars:]
