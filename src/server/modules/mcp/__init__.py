"""MCP Module - External AI Agent Interface

This module implements the Model Context Protocol (MCP) server for the CMMS,
exposing the full CMMS surface to external AI agents with mandatory guardrails:
- Confirmation gates for destructive operations
- Dry-run validation
- Rate limits per session/tool
- Session-hour ceilings
- Safety flag guards
- Batch rollback capability

Transports:
- stdio: For local/sidecar agents
- HTTP: Streamable HTTP/SSE transport behind nginx /mcp/*

Authentication:
- JWT path: Uses AUTH.verify_access_token
- API-key path: Scoped key bound to one organization_id + role
- SYS_ADMIN role REJECTED unconditionally

Depends on: core, auth, tenancy, assets, cycles, templates, workorders, tickets, reports, ai, cache
"""

from .service import (
    McpModule,
    create_server,
    serve_stdio,
    serve_http,
    authenticate,
    authorize,
    register_resources,
    register_tools,
    register_prompts,
    confirmation_gate,
    apply_dry_run,
    rate_limit_session,
    check_ceiling,
    safety_flag_guard,
    batch_rollback,
    audit_call,
    health_check,
    # Session type
    McpSession,
    # Tool categories
    AssetTools,
    CycleTools,
    CounterTools,
    WorkOrderTools,
    TicketTools,
    AuthoringTools,
    ReportingTools,
    # Exceptions
    McpError,
    ConfirmationRequired,
    DryRunResult,
    RateLimitExceeded,
    CeilingExceeded,
    SafetyViolation,
)

__all__ = [
    "McpModule",
    "create_server",
    "serve_stdio",
    "serve_http",
    "authenticate",
    "authorize",
    "register_resources",
    "register_tools",
    "register_prompts",
    "confirmation_gate",
    "apply_dry_run",
    "rate_limit_session",
    "check_ceiling",
    "safety_flag_guard",
    "batch_rollback",
    "audit_call",
    "health_check",
    "McpSession",
    "AssetTools",
    "CycleTools",
    "CounterTools",
    "WorkOrderTools",
    "TicketTools",
    "AuthoringTools",
    "ReportingTools",
    "McpError",
    "ConfirmationRequired",
    "DryRunResult",
    "RateLimitExceeded",
    "CeilingExceeded",
    "SafetyViolation",
]
