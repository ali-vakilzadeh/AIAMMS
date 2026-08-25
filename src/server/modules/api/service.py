"""API Module - FastAPI HTTP surface with middleware chain and error handling."""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from datetime import datetime, timezone
from enum import Enum

from fastapi import FastAPI, Request, Response, status, Depends, HTTPException
from fastapi.middleware import Middleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from core.module_base import ModuleBase, ModuleContext, HealthStatus
from core.health import HealthReport
from core.settings import module_settings
from core.logger import get_logger
from core.utils import new_request_id, utcnow


logger = get_logger("api")


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class RequestContext:
    """Request context extracted from verified claims."""
    org_id: Any | None = None
    user_id: Any | None = None
    role: str | None = None
    request_id: str | None = None
    timezone: str | None = None


class ErrorEnvelope(BaseModel):
    """Standard error response envelope."""
    error_code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class PaginatedResponse(BaseModel):
    """Standard paginated response envelope."""
    data: list[Any]
    page: int
    page_size: int
    total: int


# =============================================================================
# Domain Exceptions
# =============================================================================

class QuotaExceeded(Exception):
    """Tier quota exceeded."""
    def __init__(self, message: str = "Quota exceeded"):
        self.message = message
        super().__init__(message)


class PaymentOverdue(Exception):
    """Organization payment overdue."""
    def __init__(self, message: str = "Payment overdue"):
        self.message = message
        super().__init__(message)


class NotFoundError(Exception):
    """Resource not found."""
    def __init__(self, message: str = "Not found"):
        self.message = message
        super().__init__(message)


class ForbiddenError(Exception):
    """Access forbidden."""
    def __init__(self, message: str = "Forbidden"):
        self.message = message
        super().__init__(message)


# =============================================================================
# Global State
# =============================================================================

_app: Optional[FastAPI] = None
_middleware_registry: list[tuple[int, Middleware]] = []  # (order, middleware)
_router_registry: dict[str, APIRouter] = {}  # prefix -> router


# =============================================================================
# Core Functions
# =============================================================================

def create_app(title: str = "CMMS SaaS API", version: str = "1.0.0") -> FastAPI:
    """
    Create FastAPI application factory.
    
    Args:
        title: API title for OpenAPI
        version: API version
        
    Returns:
        FastAPI application instance
        
    Features:
        - OpenAPI at /api/v1/openapi.json (toggle via CMMS_API__OPENAPI_ENABLED)
        - Central exception handlers
        - No static file mounts
    """
    global _app
    
    settings = module_settings("api")
    openapi_enabled = getattr(settings, "openapi_enabled", True) if settings else True
    
    _app = FastAPI(
        title=title,
        version=version,
        openapi_url="/api/v1/openapi.json" if openapi_enabled else None,
        docs_url="/api/v1/docs" if openapi_enabled else None,
        redoc_url="/api/v1/redoc" if openapi_enabled else None,
    )
    
    # Install central exception handlers
    _app.add_exception_handler(Exception, _global_exception_handler)
    _app.add_exception_handler(QuotaExceeded, _quota_exceeded_handler)
    _app.add_exception_handler(PaymentOverdue, _payment_overdue_handler)
    _app.add_exception_handler(NotFoundError, _not_found_handler)
    _app.add_exception_handler(ForbiddenError, _forbidden_handler)
    _app.add_exception_handler(HTTPException, _http_exception_handler)
    
    logger.info(f"Created FastAPI app: {title} v{version}")
    return _app


def register_router(router: APIRouter, prefix: str, tags: Optional[list[str]] = None) -> None:
    """
    Mount router under /api/v1/{prefix}.
    
    Args:
        router: FastAPI APIRouter instance
        prefix: URL prefix (e.g., "auth", "assets")
        tags: OpenAPI tags
        
    Raises:
        ValueError: If prefix already registered
    """
    global _router_registry
    
    if prefix in _router_registry:
        raise ValueError(f"Router prefix '{prefix}' already registered")
    
    full_prefix = f"/api/v1/{prefix}"
    _app.include_router(router, prefix=full_prefix, tags=tags or [])
    _router_registry[prefix] = router
    
    logger.info(f"Registered router: {full_prefix}")


def add_middleware(factory: Callable[[], Middleware], order: int) -> None:
    """
    Register middleware with ordering.
    
    Args:
        factory: Callable returning Middleware instance
        order: Execution order (lower = earlier)
        
    Middleware executes in ascending order.
    Standard order:
        - request_id: 10
        - cors: 20
        - auth_hook: 30
        - org_scope_hook: 40
        - rate_limit: 50
    """
    _middleware_registry.append((order, factory))
    logger.debug(f"Registered middleware at order {order}")


def install_middleware_chain() -> None:
    """
    Install middleware chain in fixed order.
    
    Order: request_id(10) -> cors(20) -> auth_hook(30) -> org_scope_hook(40) -> rate_limit(50)
    
    Called at startup after all middleware registered.
    """
    global _app
    
    # Sort by order
    _middleware_registry.sort(key=lambda x: x[0])
    
    for order, factory in _middleware_registry:
        middleware = factory()
        _app.user_middleware.append(middleware)
        logger.info(f"Installed middleware at order {order}")


async def error_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Map domain exceptions to status codes with standard envelope.
    
    Args:
        request: FastAPI request
        exc: Exception instance
        
    Returns:
        JSONResponse with {error_code, message, details}
        
    Mappings:
        - QuotaExceeded -> 403 TIER_LIMIT_REACHED
        - NotFound -> 404 NOT_FOUND
        - Forbidden -> 403 FORBIDDEN
        - PaymentOverdue -> 403 ORG_PAYMENT_OVERDUE
    """
    if isinstance(exc, QuotaExceeded):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error_code": "TIER_LIMIT_REACHED",
                "message": exc.message,
                "details": {}
            }
        )
    elif isinstance(exc, PaymentOverdue):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error_code": "ORG_PAYMENT_OVERDUE",
                "message": exc.message,
                "details": {}
            }
        )
    elif isinstance(exc, NotFoundError):
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error_code": "NOT_FOUND",
                "message": exc.message,
                "details": {}
            }
        )
    elif isinstance(exc, ForbiddenError):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error_code": "FORBIDDEN",
                "message": exc.message,
                "details": {}
            }
        )
    else:
        # Generic error - never leak stack traces
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error_code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
                "details": {}
            }
        )


async def paginate(
    stmt: Any,
    session: AsyncSession,
    page: int = 1,
    page_size: int = 50
) -> PaginatedResponse:
    """
    Apply pagination with LIMIT/OFFSET + COUNT.
    
    Args:
        stmt: SQLAlchemy select statement
        session: AsyncSession
        page: Page number (1-indexed)
        page_size: Items per page (clamped 1..200)
        
    Returns:
        PaginatedResponse with data, page, page_size, total
        
    Clamps page_size to 1..200 range.
    """
    # Clamp page_size
    page_size = max(1, min(200, page_size))
    page = max(1, page)
    
    # Get total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await session.execute(count_stmt)
    total = total_result.scalar() or 0
    
    # Apply offset/limit
    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)
    
    result = await session.execute(stmt)
    data = result.scalars().all() if hasattr(result, 'scalars') else result.all()
    
    return PaginatedResponse(
        data=data,
        page=page,
        page_size=page_size,
        total=total
    )


def require(action: str, resource: Optional[str] = None) -> Callable:
    """
    Endpoint guard delegating to AUTH.rbac_can.
    
    Args:
        action: Required action (e.g., "read", "write", "delete")
        resource: Optional resource identifier
        
    Returns:
        FastAPI Depends callable
        
    Usage:
        @router.get("/items")
        async def get_items(ctx: RequestContext = Depends(require("read", "items"))):
            ...
    """
    async def dependency(request: Request) -> RequestContext:
        # Delegate to AUTH module's rbac service
        from core.registry import get_service
        
        try:
            auth_service = get_service("auth")
            ctx = request_context(request)
            
            # Check RBAC
            can_access = await auth_service.rbac_can(ctx, action, resource)
            if not can_access:
                raise ForbiddenError(f"Access denied: {action} on {resource}")
            
            return ctx
        except Exception as e:
            logger.error(f"RBAC check failed: {e}")
            raise ForbiddenError("Access denied")
    
    return Depends(dependency)


def request_context(request: Request) -> RequestContext:
    """
    Extract verified claims into RequestContext.
    
    Args:
        request: FastAPI request with state populated by auth middleware
        
    Returns:
        RequestContext with org_id, user_id, role, request_id, timezone
        
    Expects request.state.claims to be set by auth_hook middleware.
    """
    claims = getattr(request.state, "claims", {}) or {}
    
    return RequestContext(
        org_id=claims.get("organization_id"),
        user_id=claims.get("sub") or claims.get("user_id"),
        role=claims.get("role"),
        request_id=getattr(request.state, "request_id", new_request_id()),
        timezone=claims.get("timezone", "UTC")
    )


def cors_config() -> dict:
    """
    CORS configuration from CMMS_API__CORS_ORIGINS.
    
    Returns:
        dict with CORS settings including credentials=true
        
    Reads origins from CMMS_API__CORS_ORIGINS (comma-separated).
    """
    settings = module_settings("api")
    origins_str = getattr(settings, "cors_origins", "*") if settings else "*"
    
    if origins_str == "*":
        origins = ["*"]
    else:
        origins = [o.strip() for o in origins_str.split(",")]
    
    return {
        "allow_origins": origins,
        "allow_credentials": True,
        "allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        "allow_headers": ["Authorization", "Content-Type", "X-Request-ID"],
    }


def serve(host: str = "0.0.0.0", port: int = 8000, workers: int = 4) -> None:
    """
    Uvicorn server helper.
    
    Args:
        host: Bind address
        port: Port number
        workers: Worker count
    """
    import uvicorn
    
    logger.info(f"Starting API server on {host}:{port} with {workers} workers")
    
    uvicorn.run(
        "modules.api.service:_app",
        host=host,
        port=port,
        workers=workers,
        log_level="info"
    )


# =============================================================================
# Exception Handlers
# =============================================================================

async def _global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unhandled exceptions with safe error envelope."""
    logger.exception(f"Unhandled exception: {exc}")
    return await error_handler(request, exc)


async def _quota_exceeded_handler(request: Request, exc: QuotaExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={
            "error_code": "TIER_LIMIT_REACHED",
            "message": exc.message,
            "details": {}
        }
    )


async def _payment_overdue_handler(request: Request, exc: PaymentOverdue) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={
            "error_code": "ORG_PAYMENT_OVERDUE",
            "message": exc.message,
            "details": {}
        }
    )


async def _not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "error_code": "NOT_FOUND",
            "message": exc.message,
            "details": {}
        }
    )


async def _forbidden_handler(request: Request, exc: ForbiddenError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={
            "error_code": "FORBIDDEN",
            "message": exc.message,
            "details": {}
        }
    )


async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error_code": f"HTTP_{exc.status_code}",
            "message": exc.detail,
            "details": {}
        }
    )


# =============================================================================
# Published Port
# =============================================================================

class HttpApi:
    """Published port for HTTP API operations."""
    
    @staticmethod
    def get_app() -> FastAPI:
        return _app
    
    @staticmethod
    def register_router(router: APIRouter, prefix: str, tags: Optional[list[str]] = None) -> None:
        register_router(router, prefix, tags)
    
    @staticmethod
    def add_middleware(factory: Callable[[], Middleware], order: int) -> None:
        add_middleware(factory, order)
    
    @staticmethod
    def install_middleware_chain() -> None:
        install_middleware_chain()
    
    @staticmethod
    async def handle_error(request: Request, exc: Exception) -> JSONResponse:
        return await error_handler(request, exc)
    
    @staticmethod
    def get_request_context(request: Request) -> RequestContext:
        return request_context(request)


# =============================================================================
# Module Implementation
# =============================================================================

class APIModule(ModuleBase):
    """API module implementing ModuleBase protocol."""
    
    name = "api"
    version = "1.0.0"
    dependencies: tuple[str, ...] = ("core",)
    optional_dependencies: tuple[str, ...] = ("auth", "tenancy", "cache")
    profiles: tuple[str, ...] = ("api", "all-in-one")
    
    async def configure(self, settings: Any) -> None:
        """Configure API module."""
        logger.info("Configuring API module")
        
    async def initialize(self, ctx: ModuleContext) -> None:
        """Initialize FastAPI app and middleware chain."""
        logger.info("Initializing API module")
        
        create_app()
        install_middleware_chain()
        
        # Register service port
        from core.registry import register_service
        register_service("api", HttpApi(), HttpApi)
        
    async def start(self) -> None:
        """Start API module."""
        logger.info("API module started")
        
    async def stop(self) -> None:
        """Stop API module."""
        global _app
        logger.info("Stopping API module")
        _app = None
        
    async def health(self) -> HealthReport:
        """Report API health."""
        checks = []
        overall_status = HealthStatus.OK
        ts = utcnow()
        
        if _app is None:
            return HealthReport(
                module="api",
                status=HealthStatus.UNAVAILABLE,
                checks=[{"name": "app", "status": "UNAVAILABLE", "detail": "App not initialized"}],
                ts=ts,
            )
        
        checks.append({
            "name": "app",
            "status": "OK",
            "detail": "FastAPI app initialized"
        })
        
        return HealthReport(
            module="api",
            status=overall_status,
            checks=checks,
            ts=ts,
        )
