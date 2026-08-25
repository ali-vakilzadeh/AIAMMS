"""Tenancy module: Organizations, memberships, invitations, quotas, and payment states."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, Field

from ...shared.types import RequestContext, Role, DomainError
from ...core.event_bus import get_event_bus
from ...core.module_base import ModuleBase
from ...core.registry import get_service

logger = logging.getLogger(__name__)


# Additional type aliases for tenancy module
MembershipRole = Role  # Use existing Role enum
PaymentState = str  # 'current', 'overdue', 'cancelled'
SubscriptionTier = str  # 'free', 'pro', 'ultimate'
Organization = dict  # Organization data structure


# Exception classes (mirroring shared/types.py patterns)
class ValidationError(DomainError):
    """Validation error."""
    def __init__(self, message: str):
        super().__init__(
            error_code="VALIDATION_ERROR",
            message=message,
        )


class NotFoundError(DomainError):
    """Resource not found."""
    def __init__(self, message: str = "Resource not found"):
        super().__init__(
            error_code="NOT_FOUND",
            message=message,
        )


class ForbiddenError(DomainError):
    """Access denied."""
    def __init__(self, message: str = "Access denied"):
        super().__init__(
            error_code="FORBIDDEN",
            message=message,
        )


class QuotaExceededError(DomainError):
    """Tier quota exceeded."""
    def __init__(self, message: str):
        super().__init__(
            error_code="TIER_LIMIT_REACHED",
            message=message,
        )


async def emit_event(event_name: str, payload: dict) -> None:
    """Emit an event via the event bus."""
    await get_event_bus().publish(event_name, payload)


# =============================================================================
# Pydantic Models
# =============================================================================


class OrganizationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    logo: Optional[str] = None
    contact_email: Optional[str] = None
    timezone: str = Field(default="UTC", max_length=64)
    custom_fields: Dict[str, Any] = Field(default_factory=dict)


class OrganizationUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    logo: Optional[str] = None
    contact_email: Optional[str] = None
    timezone: Optional[str] = None
    custom_fields: Optional[Dict[str, Any]] = None


class InvitationCreate(BaseModel):
    email: str = Field(..., min_length=1)
    role: MembershipRole


class InvitationAccept(BaseModel):
    token: str


class MembershipChange(BaseModel):
    org_id: UUID
    role: MembershipRole


class TierQuotaResponse(BaseModel):
    tier_name: str
    quota: int
    description: str


# =============================================================================
# Database Tables (SQLAlchemy models would be defined here in production)
# For now, we use the DB service directly
# =============================================================================

TABLES = [
    """
    CREATE TABLE IF NOT EXISTS organizations (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name VARCHAR(255) NOT NULL,
        logo VARCHAR(512),
        contact_email VARCHAR(255),
        timezone VARCHAR(64) DEFAULT 'UTC',
        custom_fields JSONB DEFAULT '{}',
        subscription_tier VARCHAR(64) DEFAULT 'free',
        payment_state VARCHAR(64) DEFAULT 'current',
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        created_by UUID REFERENCES users(id),
        root_zone_id UUID
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS organization_custom_fields (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        field_key VARCHAR(128) NOT NULL,
        field_value JSONB NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(organization_id, field_key)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS user_organization_memberships (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        role VARCHAR(64) NOT NULL DEFAULT 'member',
        joined_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(user_id, organization_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS invitations (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        email VARCHAR(255) NOT NULL,
        role VARCHAR(64) NOT NULL,
        token VARCHAR(128) UNIQUE NOT NULL,
        inviter_id UUID REFERENCES users(id),
        status VARCHAR(64) DEFAULT 'pending',
        expires_at TIMESTAMPTZ NOT NULL,
        accepted_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS subscription_tiers (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name VARCHAR(64) UNIQUE NOT NULL,
        quota_limit INTEGER NOT NULL,
        description TEXT,
        price_cents INTEGER DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS payment_states (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID UNIQUE NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        state VARCHAR(64) NOT NULL DEFAULT 'current',
        last_payment_date TIMESTAMPTZ,
        next_billing_date TIMESTAMPTZ,
        overdue_since TIMESTAMPTZ,
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );
    """,
]

# Default subscription tiers
DEFAULT_TIERS = [
    ("free", 100, "Free tier with basic features"),
    ("pro", 1000, "Professional tier with expanded limits"),
    ("ultimate", -1, "Unlimited tier for enterprise"),
]


# =============================================================================
# Module Class
# =============================================================================


class TenancyModule(ModuleBase):
    """
    Tenancy module managing organizations, memberships, invitations, and quotas.
    
    Provides multi-tenancy support with organization-scoped data access,
    role-based membership management, and quota enforcement based on
    subscription tiers.
    """

    name = "tenancy"
    version = "1.0.0"

    def __init__(self):
        super().__init__()
        self.db = None
        self.email = None
        self.worker = None
        self.router = APIRouter(prefix="/tenancy", tags=["tenancy"])
        self._setup_routes()

    def _setup_routes(self):
        """Register API routes for tenancy operations."""
        
        @self.router.post("/orgs", status_code=status.HTTP_201_CREATED)
        async def api_create_organization(
            data: OrganizationCreate,
            request: Request = ...,
        ):
            from .service import get_service, request_context
            ctx = request_context(request)
            return await create_organization(ctx, data.model_dump())

        @self.router.get("/orgs/{org_id}")
        async def api_get_organization(
            org_id: UUID,
            request: Request = ...,
        ):
            from .service import get_service, request_context
            ctx = request_context(request)
            return await get_organization(ctx, org_id)

        @self.router.patch("/orgs/{org_id}")
        async def api_update_organization(
            org_id: UUID,
            patch: OrganizationUpdate,
            request: Request = ...,
        ):
            from .service import get_service, request_context
            ctx = request_context(request)
            return await update_organization(ctx, org_id, patch.model_dump(exclude_unset=True))

        @self.router.post("/invitations")
        async def api_send_invitation(
            data: InvitationCreate,
            request: Request = ...,
        ):
            from .service import get_service, request_context
            ctx = request_context(request)
            # Requires org_id from context or body
            if not ctx.org_id:
                raise ValidationError("Organization ID required")
            return await send_invitation(ctx, ctx.org_id, data.email, data.role)

        @self.router.post("/invitations/accept")
        async def api_accept_invitation(data: InvitationAccept):
            return await accept_invitation(data.token)

        @self.router.get("/membership")
        async def api_get_membership(
            request: Request = ...,
        ):
            from .service import get_service, request_context
            ctx = request_context(request)
            if not ctx.user_id:
                raise ForbiddenError("Authentication required")
            return await get_membership(ctx, ctx.user_id)

        @self.router.get("/tiers/{tier_name}/quota")
        async def api_get_tier_quota(tier_name: str):
            quota = get_tier_quota(tier_name)
            tier_info = {
                "free": {"quota": 100, "description": "Free tier"},
                "pro": {"quota": 1000, "description": "Pro tier"},
                "ultimate": {"quota": -1, "description": "Unlimited"},
            }.get(tier_name, {"quota": 100, "description": "Unknown tier"})
            return {"tier_name": tier_name, "quota": quota, "description": tier_info["description"]}

    async def configure(self, config: Dict[str, Any]) -> None:
        """Configure tenancy module."""
        self.config = config
        logger.info("Tenancy module configured")

    async def initialize(self) -> None:
        """Initialize tenancy module: create tables, seed tiers."""
        self.db = get_service("db")
        self.email = get_service("email")
        self.worker = get_service("worker")

        # Create tables
        async with self.db.pool.acquire() as conn:
            for table_sql in TABLES:
                await conn.execute(table_sql)
            
            # Seed default tiers
            for tier_name, quota, desc in DEFAULT_TIERS:
                await conn.execute(
                    """
                    INSERT INTO subscription_tiers (name, quota_limit, description)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (name) DO NOTHING
                    """,
                    tier_name, quota, desc,
                )

        logger.info("Tenancy module initialized")

    async def start(self) -> None:
        """Start tenancy module: register background tasks."""
        # Register hourly task to expire invitations
        if self.worker:
            await self.worker.register_beat(
                "expire_invitations_hourly",
                "tenancy.expire_invitations",
                schedule={"hour": "*", "minute": 0},  # Every hour at minute 0
            )
        logger.info("Tenancy module started")

    async def stop(self) -> None:
        """Stop tenancy module."""
        logger.info("Tenancy module stopped")

    async def health(self) -> Dict[str, Any]:
        """Check tenancy module health."""
        try:
            async with self.db.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return {"status": "healthy", "db": "connected"}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}


# =============================================================================
# Core Functions
# =============================================================================


async def create_organization(ctx: RequestContext, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a new organization.
    
    - SYS_ADMIN can create any org
    - First org for a user is free (auto-assigned)
    - Creates root zone linked to org
    - Emits org.created event
    """
    db = get_service("db")
    
    # Check permissions: SYS_ADMIN or first org
    if not ctx.is_sys_admin:
        # Check if user already has an org (first org is free)
        async with db.pool.acquire() as conn:
            existing = await conn.fetchval(
                "SELECT COUNT(*) FROM user_organization_memberships WHERE user_id = $1",
                ctx.user_id,
            )
            if existing > 0:
                raise ForbiddenError("Only SYS_ADMIN or users without org can create organizations")

    org_id = uuid4()
    root_zone_id = uuid4()  # Will be linked to zones module
    
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            # Create organization
            await conn.execute(
                """
                INSERT INTO organizations 
                (id, name, logo, contact_email, timezone, custom_fields, created_by, root_zone_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                org_id,
                data.get("name"),
                data.get("logo"),
                data.get("contact_email"),
                data.get("timezone", "UTC"),
                data.get("custom_fields", {}),
                ctx.user_id,
                root_zone_id,
            )
            
            # Add creator as MANAGER
            await conn.execute(
                """
                INSERT INTO user_organization_memberships (user_id, organization_id, role)
                VALUES ($1, $2, 'manager')
                """,
                ctx.user_id,
                org_id,
            )
            
            # Initialize payment state
            await conn.execute(
                """
                INSERT INTO payment_states (organization_id, state)
                VALUES ($1, 'current')
                """,
                org_id,
            )

    # Emit event
    await emit_event(
        "org.created",
        {
            "organization_id": str(org_id),
            "name": data.get("name"),
            "created_by": str(ctx.user_id),
            "root_zone_id": str(root_zone_id),
        },
    )

    logger.info(f"Organization created: {org_id} by user {ctx.user_id}")
    
    return {
        "id": str(org_id),
        "name": data.get("name"),
        "root_zone_id": str(root_zone_id),
        "message": "Organization created successfully",
    }


async def get_organization(ctx: RequestContext, org_id: UUID) -> Dict[str, Any]:
    """
    Get organization details (org-scoped).
    
    - Requires membership in the organization
    - Returns org profile with membership info
    """
    db = get_service("db")
    
    # Verify membership
    async with db.pool.acquire() as conn:
        membership = await conn.fetchrow(
            """
            SELECT role FROM user_organization_memberships
            WHERE user_id = $1 AND organization_id = $2
            """,
            ctx.user_id,
            org_id,
        )
        
        if not membership:
            raise NotFoundError("Organization not found or access denied")
        
        org = await conn.fetchrow(
            """
            SELECT id, name, logo, contact_email, timezone, custom_fields,
                   subscription_tier, payment_state, created_at, updated_at
            FROM organizations
            WHERE id = $1
            """,
            org_id,
        )
        
        if not org:
            raise NotFoundError("Organization not found")

    return {
        "id": str(org["id"]),
        "name": org["name"],
        "logo": org["logo"],
        "contact_email": org["contact_email"],
        "timezone": org["timezone"],
        "custom_fields": org["custom_fields"],
        "subscription_tier": org["subscription_tier"],
        "payment_state": org["payment_state"],
        "your_role": membership["role"],
        "created_at": org["created_at"].isoformat() if org["created_at"] else None,
        "updated_at": org["updated_at"].isoformat() if org["updated_at"] else None,
    }


async def update_organization(
    ctx: RequestContext, org_id: UUID, patch: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Update organization profile.
    
    - Requires MANAGER role
    - Audited update
    - Emits org.updated event
    """
    db = get_service("db")
    
    # Verify MANAGER role
    async with db.pool.acquire() as conn:
        membership = await conn.fetchrow(
            """
            SELECT role FROM user_organization_memberships
            WHERE user_id = $1 AND organization_id = $2
            """,
            ctx.user_id,
            org_id,
        )
        
        if not membership or membership["role"] not in ["manager", "owner"]:
            raise ForbiddenError("MANAGER role required")
        
        # Build dynamic update
        updates = []
        values = []
        for key in ["name", "logo", "contact_email", "timezone", "custom_fields"]:
            if key in patch:
                updates.append(f"{key} = ${len(values) + 1}")
                values.append(patch[key])
        
        if not updates:
            raise ValidationError("No fields to update")
        
        updates.append("updated_at = NOW()")
        values.append(org_id)
        
        await conn.execute(
            f"""
            UPDATE organizations
            SET {', '.join(updates)}
            WHERE id = ${len(values)}
            """,
            *values,
        )

    # Emit event
    await emit_event(
        "org.updated",
        {
            "organization_id": str(org_id),
            "updated_by": str(ctx.user_id),
            "changes": patch,
        },
    )

    logger.info(f"Organization {org_id} updated by {ctx.user_id}")
    
    return {"message": "Organization updated", "changes": patch}


async def can_create_ticket(org_id: UUID) -> bool:
    """
    Check if organization can create tickets.
    
    - Checks payment_state != OVERDUE
    - Used by TICKETS module gate
    """
    db = get_service("db")
    
    async with db.pool.acquire() as conn:
        payment_state = await conn.fetchval(
            "SELECT payment_state FROM organizations WHERE id = $1",
            org_id,
        )
        
        if not payment_state:
            raise NotFoundError("Organization not found")
        
        return payment_state != "overdue"


async def can_create_service_point(org_id: UUID) -> bool:
    """
    Check if organization can create service points.
    
    - Checks tier quota (Free<=100, Pro<=1000, Ultimate=unlimited)
    - Counts active service_points
    - Raises QuotaExceededError if exceeded
    """
    db = get_service("db")
    
    async with db.pool.acquire() as conn:
        org = await conn.fetchrow(
            "SELECT subscription_tier FROM organizations WHERE id = $1",
            org_id,
        )
        
        if not org:
            raise NotFoundError("Organization not found")
        
        tier_name = org["subscription_tier"]
        quota = get_tier_quota(tier_name)
        
        # Unlimited quota
        if quota < 0:
            return True
        
        # Count active service points (assuming service_points table exists)
        try:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM service_points WHERE organization_id = $1 AND active = true",
                org_id,
            )
        except Exception:
            # Table might not exist yet (zones module not loaded)
            count = 0
        
        if count >= quota:
            raise QuotaExceededError(
                f"Organization quota exceeded: {count}/{quota} service points"
            )
        
        return True


def get_tier_quota(tier_name: str) -> int:
    """
    Get quota limit for subscription tier.
    
    - free: 100
    - pro: 1000
    - ultimate: -1 (unlimited)
    """
    quotas = {
        "free": 100,
        "pro": 1000,
        "ultimate": -1,  # unlimited
    }
    return quotas.get(tier_name.lower(), 100)  # default to free tier


async def send_invitation(
    ctx: RequestContext, org_id: UUID, email: str, role: MembershipRole
) -> Dict[str, Any]:
    """
    Send organization invitation.
    
    - Requires MANAGER role
    - Creates invitation with single-use token (14d expiry)
    - Sends invitation email template
    - Emits invitation.sent event
    """
    db = get_service("db")
    email_service = get_service("email")
    
    # Verify MANAGER role
    async with db.pool.acquire() as conn:
        membership = await conn.fetchrow(
            """
            SELECT role FROM user_organization_memberships
            WHERE user_id = $1 AND organization_id = $2
            """,
            ctx.user_id,
            org_id,
        )
        
        if not membership or membership["role"] not in ["manager", "owner"]:
            raise ForbiddenError("MANAGER role required to send invitations")
        
        # Generate token
        token = str(uuid4())
        expires_at = datetime.utcnow() + timedelta(days=14)
        
        # Create invitation
        await conn.execute(
            """
            INSERT INTO invitations (organization_id, email, role, token, inviter_id, expires_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            org_id,
            email,
            role.value if hasattr(role, "value") else role,
            token,
            ctx.user_id,
            expires_at,
        )

    # Send invitation email
    if email_service:
        await email_service.send_template(
            to_email=email,
            template_name="invitation",
            context={
                "email": email,
                "organization_name": ctx.organization_name or "Unknown",
                "role": role,
                "accept_url": f"/tenancy/invitations/accept?token={token}",
                "expires_in_days": 14,
            },
        )

    # Emit event
    await emit_event(
        "invitation.sent",
        {
            "organization_id": str(org_id),
            "email": email,
            "role": role.value if hasattr(role, "value") else role,
            "inviter_id": str(ctx.user_id),
            "token": token,
        },
    )

    logger.info(f"Invitation sent to {email} for org {org_id}")
    
    return {
        "message": "Invitation sent",
        "email": email,
        "expires_at": expires_at.isoformat(),
    }


async def accept_invitation(token: str) -> Dict[str, Any]:
    """
    Accept organization invitation.
    
    - Validates token (not expired, pending status)
    - Adds user to org membership
    - If user has existing membership, handles replacement (leave old org)
    - Emits invitation.accepted event
    """
    db = get_service("db")
    
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            # Find invitation
            invitation = await conn.fetchrow(
                """
                SELECT id, organization_id, email, role, status, expires_at
                FROM invitations
                WHERE token = $1
                """,
                token,
            )
            
            if not invitation:
                raise NotFoundError("Invalid invitation token")
            
            if invitation["status"] != "pending":
                raise ValidationError(f"Invitation already {invitation['status']}")
            
            if invitation["expires_at"] < datetime.utcnow():
                raise ValidationError("Invitation expired")
            
            # Get current user from context (would be set after auth)
            # In real scenario, user_id comes from JWT after token validation
            # For now, we assume the email matches the authenticated user
            user_email = invitation["email"]
            
            # Find user by email (simplified - in production, query users table)
            user = await conn.fetchrow(
                "SELECT id FROM users WHERE email = $1",
                user_email,
            )
            
            if not user:
                raise NotFoundError(f"No user found with email {user_email}")
            
            user_id = user["id"]
            org_id = invitation["organization_id"]
            role = invitation["role"]
            
            # Check existing membership
            existing = await conn.fetchrow(
                """
                SELECT organization_id, role FROM user_organization_memberships
                WHERE user_id = $1
                """,
                user_id,
            )
            
            if existing:
                # Leave old org (emit event in production)
                await conn.execute(
                    """
                    DELETE FROM user_organization_memberships
                    WHERE user_id = $1 AND organization_id = $2
                    """,
                    user_id,
                    existing["organization_id"],
                )
                logger.info(f"User {user_id} left org {existing['organization_id']}")
            
            # Add to new org
            await conn.execute(
                """
                INSERT INTO user_organization_memberships (user_id, organization_id, role)
                VALUES ($1, $2, $3)
                """,
                user_id,
                org_id,
                role,
            )
            
            # Mark invitation as accepted
            await conn.execute(
                """
                UPDATE invitations
                SET status = 'accepted', accepted_at = NOW()
                WHERE id = $1
                """,
                invitation["id"],
            )

    # Emit event
    await emit_event(
        "invitation.accepted",
        {
            "user_id": str(user_id),
            "organization_id": str(org_id),
            "role": role,
        },
    )

    logger.info(f"User {user_id} accepted invitation to org {org_id}")
    
    return {
        "message": "Invitation accepted",
        "organization_id": str(org_id),
        "role": role,
    }


async def expire_invitations() -> Dict[str, int]:
    """
    Background task: Expire pending invitations past their expiry date.
    
    - Soft-deletes expired invitations
    - Emits invitation.expired events
    - Runs hourly via worker beat schedule
    """
    db = get_service("db")
    
    async with db.pool.acquire() as conn:
        # Find expired invitations
        expired = await conn.fetch(
            """
            SELECT id, organization_id, email, role
            FROM invitations
            WHERE status = 'pending' AND expires_at < NOW()
            """,
        )
        
        expired_count = len(expired)
        
        for inv in expired:
            # Mark as expired
            await conn.execute(
                """
                UPDATE invitations
                SET status = 'expired'
                WHERE id = $1
                """,
                inv["id"],
            )
            
            # Emit event
            await emit_event(
                "invitation.expired",
                {
                    "organization_id": str(inv["organization_id"]),
                    "email": inv["email"],
                    "role": inv["role"],
                },
            )
    
    logger.info(f"Expired {expired_count} invitations")
    
    return {"expired_count": expired_count}


async def get_membership(ctx: RequestContext, user_id: UUID) -> Dict[str, Any]:
    """
    Get user's current organization membership.
    
    - Returns membership with org info and role
    """
    db = get_service("db")
    
    async with db.pool.acquire() as conn:
        membership = await conn.fetchrow(
            """
            SELECT m.user_id, m.organization_id, m.role, m.joined_at,
                   o.name as org_name, o.subscription_tier, o.payment_state
            FROM user_organization_memberships m
            JOIN organizations o ON m.organization_id = o.id
            WHERE m.user_id = $1
            LIMIT 1
            """,
            user_id,
        )
        
        if not membership:
            return {"has_membership": False}

    return {
        "has_membership": True,
        "user_id": str(membership["user_id"]),
        "organization_id": str(membership["organization_id"]),
        "organization_name": membership["org_name"],
        "role": membership["role"],
        "subscription_tier": membership["subscription_tier"],
        "payment_state": membership["payment_state"],
        "joined_at": membership["joined_at"].isoformat() if membership["joined_at"] else None,
    }


async def change_membership(
    ctx: RequestContext, user_id: UUID, org_id: UUID, role: MembershipRole
) -> Dict[str, Any]:
    """
    Change user's membership role.
    
    - Requires MANAGER/SYS_ADMIN
    - Audited update
    - Emits membership.changed event
    """
    db = get_service("db")
    
    # Verify permissions
    if not ctx.is_sys_admin:
        async with db.pool.acquire() as conn:
            membership = await conn.fetchrow(
                """
                SELECT role FROM user_organization_memberships
                WHERE user_id = $1 AND organization_id = $2
                """,
                ctx.user_id,
                org_id,
            )
            
            if not membership or membership["role"] not in ["manager", "owner"]:
                raise ForbiddenError("MANAGER or SYS_ADMIN required")
    
    async with db.pool.acquire() as conn:
        # Update membership
        result = await conn.execute(
            """
            UPDATE user_organization_memberships
            SET role = $1, updated_at = NOW()
            WHERE user_id = $2 AND organization_id = $3
            """,
            role.value if hasattr(role, "value") else role,
            user_id,
            org_id,
        )
        
        if result == "UPDATE 0":
            raise NotFoundError("Membership not found")

    # Emit event
    await emit_event(
        "membership.changed",
        {
            "user_id": str(user_id),
            "organization_id": str(org_id),
            "new_role": role.value if hasattr(role, "value") else role,
            "changed_by": str(ctx.user_id),
        },
    )

    logger.info(f"Membership changed: user {user_id} role {role} in org {org_id}")
    
    return {
        "message": "Membership updated",
        "user_id": str(user_id),
        "organization_id": str(org_id),
        "new_role": role.value if hasattr(role, "value") else role,
    }


async def record_payment_overdue(org_id: UUID) -> Dict[str, Any]:
    """
    Mark organization payment as overdue.
    
    - Updates payment_state to OVERDUE
    - Emits payment.overdue event
    """
    db = get_service("db")
    
    async with db.pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE organizations
            SET payment_state = 'overdue', updated_at = NOW()
            WHERE id = $1
            """,
            org_id,
        )
        
        await conn.execute(
            """
            INSERT INTO payment_states (organization_id, state, overdue_since)
            VALUES ($1, 'overdue', NOW())
            ON CONFLICT (organization_id) DO UPDATE
            SET state = 'overdue', overdue_since = NOW(), updated_at = NOW()
            """,
            org_id,
        )

    # Emit event
    await emit_event(
        "payment.overdue",
        {"organization_id": str(org_id)},
    )

    logger.warning(f"Organization {org_id} marked as payment overdue")
    
    return {"message": "Payment state updated to overdue", "organization_id": str(org_id)}


async def clear_payment(org_id: UUID) -> Dict[str, Any]:
    """
    Clear organization payment overdue state.
    
    - Updates payment_state to CURRENT
    - Emits payment.cleared event
    """
    db = get_service("db")
    
    async with db.pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE organizations
            SET payment_state = 'current', updated_at = NOW()
            WHERE id = $1
            """,
            org_id,
        )
        
        await conn.execute(
            """
            UPDATE payment_states
            SET state = 'current', overdue_since = NULL, updated_at = NOW()
            WHERE organization_id = $1
            """,
            org_id,
        )

    # Emit event
    await emit_event(
        "payment.cleared",
        {"organization_id": str(org_id)},
    )

    logger.info(f"Organization {org_id} payment cleared")
    
    return {"message": "Payment state cleared", "organization_id": str(org_id)}


def org_scoped_query(session: Any, org_id: UUID, query: Any) -> Any:
    """
    Helper to ensure queries are organization-scoped.
    
    Usage:
        query = org_scoped_query(session, org_id, session.query(ServicePoint))
    
    This ensures all queries filter by organization_id for data isolation.
    """
    # In SQLAlchemy, this would add .filter(model.organization_id == org_id)
    # For asyncpg, callers should manually add WHERE organization_id = $1
    return query.filter_by(organization_id=org_id) if hasattr(query, "filter_by") else query
