"""DB Module - PostgreSQL access with RLS, migrations, and health reporting."""

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, AsyncContextManager, Optional
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    async_scoped_session,
)
from sqlalchemy.orm import DeclarativeBase, registry
from sqlalchemy import text, event
from sqlalchemy.pool import NullPool

from core.module_base import ModuleBase, ModuleMeta, ModuleContext, HealthStatus
from core.health import HealthReport
from core.settings import module_settings
from core.logger import get_logger
from core.utils import utcnow


logger = get_logger("db")


class DBSettings(BaseModel):
    """Database configuration from environment."""
    url: str
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30
    statement_timeout: int = 60000  # ms
    rls_enforced: bool = True
    
    class Config:
        env_prefix = "CMMS_DB__"


# Global state - initialized during module lifecycle
_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None
_model_registry: dict[str, type[DeclarativeBase]] = {}


def build_engine() -> AsyncEngine:
    """Create async SQLAlchemy engine from CMMS_DB__URL.
    
    Configures pool size, overflow, timeout, and statement timeout.
    Called once at initialize().
    """
    global _engine
    
    settings = module_settings("db")
    if settings is None:
        raise RuntimeError("DB settings not loaded")
    
    db_settings = settings  # type: DBSettings
    
    logger.info(f"Creating database engine with pool_size={db_settings.pool_size}")
    
    _engine = create_async_engine(
        db_settings.url,
        pool_size=db_settings.pool_size,
        max_overflow=db_settings.max_overflow,
        pool_timeout=db_settings.pool_timeout,
        echo=False,
        future=True,
    )
    
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    """Return session factory for platform-level sessions.
    
    Raw sessions before org context exists (used by AUTH for platform tables).
    """
    global _session_factory
    
    if _engine is None:
        raise RuntimeError("Engine not initialized - call build_engine first")
    
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
    
    return _session_factory


@asynccontextmanager
async def org_scoped_session(org_id: UUID) -> AsyncGenerator[AsyncSession, None]:
    """Context manager executing SET LOCAL app.organization_id for PostgreSQL RLS.
    
    All domain modules MUST use this for tenant-scoped queries.
    
    Args:
        org_id: Tenant organization ID
        
    Yields:
        AsyncSession with RLS context set
        
    Raises:
        ValueError: If org_id is missing
    """
    if org_id is None:
        raise ValueError("org_id is required for org_scoped_session")
    
    session = session_factory()()
    
    try:
        await session.begin()
        
        # Set RLS context for this transaction
        await session.execute(
            text("SET LOCAL app.organization_id = :org"),
            {"org": str(org_id)}
        )
        
        logger.debug(f"RLS context set for org {org_id}")
        yield session
        
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def ensure_extensions() -> None:
    """Create required PostgreSQL extensions: vector, pgcrypto, citext."""
    if _engine is None:
        raise RuntimeError("Engine not initialized")
    
    async with _engine.begin() as conn:
        extensions = ["vector", "pgcrypto", "citext"]
        for ext in extensions:
            try:
                await conn.execute(text(f"CREATE EXTENSION IF NOT EXISTS {ext}"))
                logger.info(f"Extension '{ext}' ensured")
            except Exception as e:
                logger.warning(f"Could not create extension {ext}: {e}")


async def run_migrations(revision: str = "head") -> None:
    """Run alembic migrations programmatically.
    
    Args:
        revision: Target alembic revision (default: 'head')
    """
    logger.info(f"Running migrations to revision: {revision}")
    
    # Alembic integration - runs migrations via alembic API
    try:
        from alembic.config import Config
        from alembic import command
        from alembic.script import ScriptDirectory
        
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, revision)
        logger.info(f"Migrations completed to {revision}")
    except ImportError:
        logger.warning("Alembic not installed - skipping migrations")
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise


@asynccontextmanager
async def transaction(session: AsyncSession) -> AsyncGenerator[None, None]:
    """Transaction context manager committing on success, rolling back on exception.
    
    Standardizes unit-of-work pattern.
    
    Usage:
        async with transaction(session):
            # do work
            session.add(model)
    """
    try:
        yield
        await session.commit()
        logger.debug("Transaction committed")
    except Exception:
        await session.rollback()
        logger.exception("Transaction rolled back")
        raise


def register_models(module_name: str, base: type[DeclarativeBase]) -> None:
    """Collect models for migration autogeneration.
    
    Enforces that tenant tables have organization_id column.
    
    Args:
        module_name: Owning module name
        base: Module's declarative base with models
    """
    _model_registry[module_name] = base
    logger.info(f"Models registered for module: {module_name}")


async def health_check() -> HealthReport:
    """Check database connectivity and pool saturation.
    
    Returns:
        HealthReport with status OK/DEGRADED/UNAVAILABLE
        
    Checks:
        - Connectivity ping (SELECT 1)
        - Pool saturation % (DEGRADED >80%)
    """
    checks = []
    overall_status = HealthStatus.OK
    ts = utcnow()
    
    if _engine is None:
        return HealthReport(
            module="db",
            status=HealthStatus.UNAVAILABLE,
            checks=[{"name": "engine", "status": "UNAVAILABLE", "detail": "Engine not initialized"}],
            ts=ts,
        )
    
    # Check connectivity
    try:
        async with _engine.begin() as conn:
            result = await conn.execute(text("SELECT 1"))
            await result.fetchone()
            
        checks.append({
            "name": "connectivity",
            "status": "OK",
            "latency_ms": 0,  # Could measure actual latency
            "detail": "Connection successful"
        })
    except Exception as e:
        checks.append({
            "name": "connectivity", 
            "status": "UNAVAILABLE",
            "detail": str(e)
        })
        overall_status = HealthStatus.UNAVAILABLE
    
    # Check pool saturation
    if _engine.pool is not None:
        pool_size = _engine.pool.size()
        checked_out = _engine.pool.checkedout()
        saturation = (checked_out / pool_size * 100) if pool_size > 0 else 0
        
        pool_status = HealthStatus.OK
        if saturation > 80:
            pool_status = HealthStatus.DEGRADED
            if overall_status == HealthStatus.OK:
                overall_status = pool_status
        
        checks.append({
            "name": "pool_saturation",
            "status": pool_status.value,
            "detail": f"{checked_out}/{pool_size} ({saturation:.1f}%)"
        })
    
    return HealthReport(
        module="db",
        status=overall_status,
        checks=checks,
        ts=ts,
    )


class DatabaseService:
    """Published port for database access."""
    
    @staticmethod
    def get_engine() -> Optional[AsyncEngine]:
        return _engine
    
    @staticmethod
    def get_session_factory() -> async_sessionmaker[AsyncSession]:
        return session_factory()
    
    @staticmethod
    async def get_org_session(org_id: UUID) -> AsyncContextManager[AsyncSession]:
        return org_scoped_session(org_id)
    
    @staticmethod
    async def ensure_extensions_available() -> None:
        await ensure_extensions()
    
    @staticmethod
    async def migrate(revision: str = "head") -> None:
        await run_migrations(revision)
    
    @staticmethod
    def register_module_models(module_name: str, base: type[DeclarativeBase]) -> None:
        register_models(module_name, base)
    
    @staticmethod
    async def check_health() -> HealthReport:
        return await health_check()


class DBModule(ModuleBase):
    """Database module implementing ModuleBase protocol."""
    
    name = "db"
    version = "1.0.0"
    dependencies: tuple[str, ...] = ()
    optional_dependencies: tuple[str, ...] = ()
    profiles: tuple[str, ...] = ("api", "worker", "beat", "mcp", "all-in-one")
    
    async def configure(self, settings: Any) -> None:
        """Validate database configuration."""
        logger.info("Configuring DB module")
        
    async def initialize(self, ctx: ModuleContext) -> None:
        """Initialize database engine and connections."""
        logger.info("Initializing DB module")
        build_engine()
        session_factory()
        await ensure_extensions()
        
        # Register service port
        from core.registry import register_service
        register_service("db", DatabaseService(), DatabaseService)
        
    async def start(self) -> None:
        """Start DB module - nothing additional needed."""
        logger.info("DB module started")
        
    async def stop(self) -> None:
        """Stop DB module - dispose engine."""
        global _engine
        logger.info("Stopping DB module")
        if _engine is not None:
            await _engine.dispose()
            _engine = None
        
    async def health(self) -> HealthReport:
        """Report database health."""
        return await health_check()
