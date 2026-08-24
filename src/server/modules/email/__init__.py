"""Email Module - Transactional email with SMTP and API provider adapters."""

from .service import (
    provider,
    render,
    send,
    send_template,
    health_check,
    EmailProvider,
    RenderedEmail,
    EmailService,
)

__all__ = [
    "provider",
    "render",
    "send",
    "send_template",
    "health_check",
    "EmailProvider",
    "RenderedEmail",
    "EmailService",
]
