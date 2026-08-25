"""API Module - FastAPI HTTP surface with middleware chain and error handling."""

from .service import (
    create_app,
    register_router,
    add_middleware,
    install_middleware_chain,
    error_handler,
    paginate,
    require,
    request_context,
    cors_config,
    serve,
    HttpApi,
    RequestContext,
    ErrorEnvelope,
    PaginatedResponse,
)

__all__ = [
    "create_app",
    "register_router",
    "add_middleware",
    "install_middleware_chain",
    "error_handler",
    "paginate",
    "require",
    "request_context",
    "cors_config",
    "serve",
    "HttpApi",
    "RequestContext",
    "ErrorEnvelope",
    "PaginatedResponse",
]
