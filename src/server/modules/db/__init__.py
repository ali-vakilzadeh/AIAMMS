"""DB Module - PostgreSQL access with RLS support."""

from .service import (
    build_engine,
    session_factory,
    org_scoped_session,
    ensure_extensions,
    run_migrations,
    transaction,
    register_models,
    health_check,
    DatabaseService,
)

__all__ = [
    "build_engine",
    "session_factory", 
    "org_scoped_session",
    "ensure_extensions",
    "run_migrations",
    "transaction",
    "register_models",
    "health_check",
    "DatabaseService",
]
