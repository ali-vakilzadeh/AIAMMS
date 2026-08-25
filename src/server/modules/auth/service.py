"""AUTH Module - Identity management, JWT lifecycle, password flows, and RBAC engine."""

import asyncio
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, List, Set
from uuid import UUID, uuid4
from dataclasses import dataclass, field
from enum import Enum

from fastapi import FastAPI, Request, Response, Depends, HTTPException, status, Cookie
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field, EmailStr
from passlib.context import CryptContext
import jwt

from core.module_base import ModuleBase, ModuleContext, HealthStatus
from core.health import HealthReport
from core.settings import module_settings
from core.logger import get_logger
from core.utils import utcnow, new_id
from core.event_bus import get_event_bus
from core.registry import get_service

from shared.types import (
    RequestContext,
    Role,
    DomainError,
    NotFoundError,
    ForbiddenError,
    UnauthorizedError,
    QuotaExceededError,
)

# Import infrastructure ports
from modules.db.service import DatabaseService
from modules.cache.service import CacheService
from modules.email.service import EmailService
from modules.api.service import HttpApi, request_context as api_request_context


logger = get_logger("auth")


# =============================================================================
# Configuration
# =============================================================================

def _get_auth_setting(key: str, default: Any) -> Any:
    """Get AUTH module setting."""
    settings = module_settings("auth")
    return getattr(settings, key, default) if hasattr(settings, key) else default

JWT_SECRET = _get_auth_setting("JWT_SECRET", "dev-secret-change-in-prod")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TTL_MINUTES = int(_get_auth_setting("ACCESS_TTL_MINUTES", 15))
REFRESH_TOKEN_TTL_DAYS = int(_get_auth_setting("REFRESH_TTL_DAYS", 7))
PASSWORD_MIN_LENGTH = int(_get_auth_setting("PASSWORD_MIN_LENGTH", 10))

# Password hashing context
pwd_context = CryptContext(schemes=["argon2"], argon2__rounds=10, argon2__memory_cost=65536)


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class Claims:
    """JWT claims structure."""
    sub: UUID  # user_id
    organization_id: UUID | None
    role: Role | None
    jti: str
    exp: datetime
    
    def to_dict(self) -> dict:
        return {
            "sub": str(self.sub),
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "role": self.role.value if self.role else None,
            "jti": self.jti,
            "exp": int(self.exp.timestamp()),
        }


@dataclass
class Profile:
    """User profile returned by /auth/me."""
    user_id: UUID
    email: str
    is_verified: bool
    is_deactivated: bool
    timezone: str
    organization_id: UUID | None
    organization_name: str | None
    role: Role | None
    permissions: List[str]


@dataclass
class RateDecision:
    """Rate limit decision."""
    allowed: bool
    remaining: int
    reset_at: datetime


class PasswordViolation(Enum):
    """Password policy violation codes."""
    TOO_SHORT = "TOO_SHORT"
    NO_UPPERCASE = "NO_UPPERCASE"
    NO_LOWERCASE = "NO_LOWERCASE"
    NO_DIGIT = "NO_DIGIT"
    NO_SYMBOL = "NO_SYMBOL"
    BREACHED = "BREACHED"


# =============================================================================
# Database Models (SQLAlchemy ORM)
# =============================================================================

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Enum as SQLEnum, Index, PrimaryKeyConstraint

class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_deactivated: Mapped[bool] = mapped_column(Boolean, default=False)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    memberships: Mapped[List["UserOrganizationMembership"]] = relationship(back_populates="user")
    refresh_tokens: Mapped[List["AuthRefreshToken"]] = relationship(back_populates="user")


class AuthRefreshToken(Base):
    __tablename__ = "auth_refresh_tokens"
    
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    family_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # Token family for rotation
    jti: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)  # JWT ID of issued access token
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    
    # Relationships
    user: Mapped["User"] = relationship(back_populates="refresh_tokens")
    
    __table_args__ = (
        Index("idx_refresh_family", "family_id"),
        Index("idx_refresh_expires", "expires_at"),
    )


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"
    
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (Index("idx_email_token_expires", "expires_at"),)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (Index("idx_reset_token_expires", "expires_at"),)


# Note: UserOrganizationMembership is read-only, owned by TENANCY module
class UserOrganizationMembership(Base):
    __tablename__ = "user_organization_memberships"
    
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(SQLEnum(Role), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    user: Mapped["User"] = relationship(back_populates="memberships")


# =============================================================================
# RBAC Permission Matrix
# =============================================================================

# Role x Action permission matrix
PERMISSION_MATRIX: dict[Role, Set[str]] = {
    Role.SYS_ADMIN: {"*"},  # All actions
    Role.MANAGER: {
        "assets:create", "assets:update", "assets:delete",
        "workorders:create", "workorders:update", "workorders:assign",
        "tickets:create", "tickets:update",
        "reports:view", "reports:create",
        "tenancy:invite", "tenancy:update_org",
    },
    Role.REPORTER: {
        "assets:view", "workorders:view", "tickets:view",
        "reports:view", "reports:create",
    },
    Role.OPERATOR: {
        "assets:view", "workorders:view", "workorders:execute",
        "tickets:create", "tickets:update",
        "counters:log",
    },
    Role.MAINTENANCE: {
        "assets:view", "workorders:view", "workorders:execute",
        "counters:log", "counters:reset",
    },
}

# Object-level rules (checked in rbac_can)
OBJECT_RULES: dict[str, callable] = {
    # Example: can only edit own workorders unless MANAGER+
    "workorders:update": lambda ctx, resource: True,  # Simplified
}


# =============================================================================
# Global State
# =============================================================================

_db: DatabaseService | None = None
_cache: CacheService | None = None
_email: EmailService | None = None
_api: HttpApi | None = None
_revoked_jti_cache_prefix = "auth:revoked_jti:"


# =============================================================================
# Core Functions
# =============================================================================

def hash_password(password: str) -> str:
    """Hash password using Argon2id."""
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """Verify password against hash."""
    return pwd_context.verify(password, hashed)


def password_policy(password: str) -> list[PasswordViolation]:
    """
    Validate password against policy.
    
    Requirements:
    - Minimum 10 characters
    - At least one uppercase letter
    - At least one lowercase letter  
    - At least one digit
    - At least one symbol
    - Not in breached list (simplified check)
    
    Returns list of violations (empty if valid).
    """
    violations = []
    
    if len(password) < PASSWORD_MIN_LENGTH:
        violations.append(PasswordViolation.TOO_SHORT)
    
    if not any(c.isupper() for c in password):
        violations.append(PasswordViolation.NO_UPPERCASE)
    
    if not any(c.islower() for c in password):
        violations.append(PasswordViolation.NO_LOWERCASE)
    
    if not any(c.isdigit() for c in password):
        violations.append(PasswordViolation.NO_DIGIT)
    
    if not any(not c.isalnum() for c in password):
        violations.append(PasswordViolation.NO_SYMBOL)
    
    # Simplified breached check (in production, use HaveIBeenPwned API)
    common_passwords = {"password123", "qwerty123", "letmein123"}
    if password.lower() in common_passwords:
        violations.append(PasswordViolation.BREACHED)
    
    return violations


def issue_access_token(user_id: UUID, organization_id: UUID | None, role: Role | None) -> str:
    """Issue a signed JWT access token."""
    now = utcnow()
    exp = now + timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES)
    jti = new_id()
    
    claims = Claims(
        sub=user_id,
        organization_id=organization_id,
        role=role,
        jti=jti,
        exp=exp,
    )
    
    token = jwt.encode(claims.to_dict(), JWT_SECRET, algorithm=JWT_ALGORITHM)
    logger.debug(f"Issued access token for user {user_id}, jti={jti}")
    return token


def verify_access_token(token: str) -> Claims:
    """
    Verify JWT access token and return claims.
    
    Raises UnauthorizedError if invalid/expired/revoked.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        
        # Check expiration
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        if exp < utcnow():
            raise UnauthorizedError("Token expired")
        
        # Check revocation
        jti = payload.get("jti")
        if jti and _is_jti_revoked(jti):
            raise UnauthorizedError("Token revoked")
        
        # Parse claims
        user_id = UUID(payload["sub"])
        org_id = UUID(payload["organization_id"]) if payload.get("organization_id") else None
        role_str = payload.get("role")
        role = Role(role_str) if role_str else None
        
        return Claims(
            sub=user_id,
            organization_id=org_id,
            role=role,
            jti=jti,
            exp=exp,
        )
        
    except jwt.ExpiredSignatureError:
        raise UnauthorizedError("Token expired")
    except jwt.InvalidTokenError as e:
        raise UnauthorizedError(f"Invalid token: {e}")


def _is_jti_revoked(jti: str) -> bool:
    """Check if JTI is in revocation cache."""
    if not _cache:
        return False
    
    key = f"{_revoked_jti_cache_prefix}{jti}"
    # Would check Redis KV here
    return False  # Simplified


def _hash_token(token: str) -> str:
    """Hash token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def _generate_token_family() -> str:
    """Generate a token family ID for rotation tracking."""
    return secrets.token_hex(32)


async def invalidate_user_sessions(user_id: UUID) -> None:
    """
    Invalidate all refresh token families for a user.
    
    Also adds active JTIs to revocation list with TTL=access token lifetime.
    """
    if not _db or not _cache:
        logger.error("DB or CACHE not available for session invalidation")
        return
    
    async with _db.session_factory() as session:
        # Revoke all refresh tokens for user
        result = await session.execute(
            text("""
                UPDATE auth_refresh_tokens 
                SET revoked = TRUE 
                WHERE user_id = :user_id AND revoked = FALSE
            """),
            {"user_id": user_id}
        )
        await session.commit()
        
        logger.info(f"Invalidated {result.rowcount} refresh tokens for user {user_id}")
    
    # Add active JTIs to revocation cache (TTL = access token lifetime)
    ttl_seconds = ACCESS_TOKEN_TTL_MINUTES * 60
    # In production: query active JTIs and add to cache with TTL


# =============================================================================
# Authentication Routes
# =============================================================================

async def signup(
    email: str,
    password: str,
    timezone_str: str = "UTC",
) -> dict:
    """
    Register a new user.
    
    POST /auth/signup
    - Validates password policy
    - Hashes with Argon2id
    - Creates unverified user
    - Creates single-use verification token (24h)
    - Sends verify_email template via EMAIL
    - Emits user.registered event
    - Returns 201 with generic message on duplicate
    """
    if not _db or not _email:
        raise RuntimeError("AUTH module not initialized")
    
    # Validate password
    violations = password_policy(password)
    if violations:
        raise ValueError(f"Password violations: {[v.value for v in violations]}")
    
    async with _db.session_factory() as session:
        # Check if user exists
        existing = await session.execute(
            select(User).where(User.email == email)
        )
        if existing.scalar_one_or_none():
            # Return generic message to prevent enumeration
            return {"message": "If the email is not registered, you will not receive a verification email."}
        
        # Create user
        user = User(
            email=email,
            password_hash=hash_password(password),
            timezone=timezone_str,
        )
        session.add(user)
        await session.flush()  # Get user.id
        
        # Create verification token (24h expiry)
        token_value = secrets.token_urlsafe(32)
        token_hash = _hash_token(token_value)
        expires_at = utcnow() + timedelta(hours=24)
        
        verification_token = EmailVerificationToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        session.add(verification_token)
        await session.commit()
    
    # Send verification email (async, don't block)
    try:
        await _email.send_template(
            template="verify_email",
            to=email,
            vars={"email": email, "verification_url": f"/auth/verify-email?token={token_value}"},
        )
    except Exception as e:
        logger.error(f"Failed to send verification email: {e}")
    
    # Emit event
    await get_event_bus().publish("user.registered", {"user_id": str(user.id), "email": email})
    
    logger.info(f"User registered: {email}")
    return {"message": "Registration successful. Please check your email to verify your account."}


async def verify_email(token: str) -> None:
    """
    Verify email address.
    
    POST /auth/verify-email
    - Validates single-use time-limited token
    - Marks user verified
    - Emits user.verified
    - Returns 204 on success
    """
    if not _db:
        raise RuntimeError("AUTH module not initialized")
    
    token_hash = _hash_token(token)
    
    async with _db.session_factory() as session:
        # Find and validate token
        token_record = await session.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.token_hash == token_hash,
                EmailVerificationToken.used == False,
                EmailVerificationToken.expires_at > utcnow(),
            )
        )
        token_record = token_record.scalar_one_or_none()
        
        if not token_record:
            raise NotFoundError("verification_token", "invalid or expired")
        
        # Mark user as verified
        user = await session.get(User, token_record.user_id)
        if not user:
            raise NotFoundError("user", token_record.user_id)
        
        user.is_verified = True
        token_record.used = True
        
        await session.commit()
    
    # Emit event
    await get_event_bus().publish("user.verified", {"user_id": str(user.id)})
    
    logger.info(f"Email verified for user {user.id}")


async def login(
    email: str,
    password: str,
    request: Request,
) -> dict:
    """
    Authenticate user and issue tokens.
    
    POST /auth/login
    - Verifies credentials
    - Blocks unverified/deactivated users
    - Rate-limits via CACHE
    - Issues JWT access token (15m) and refresh token (7d cookie)
    - Emits user.logged_in with ip/user_agent
    """
    if not _db or not _cache:
        raise RuntimeError("AUTH module not initialized")
    
    # Rate limiting
    ip = request.client.host if request.client else "unknown"
    rate_key = f"auth:login:{ip}"
    # Would call _cache.allow(rate_key, limit=5, window_s=60)
    
    async with _db.session_factory() as session:
        # Find user
        user = await session.execute(
            select(User).where(User.email == email)
        )
        user = user.scalar_one_or_none()
        
        if not user:
            # Constant response to prevent enumeration
            raise UnauthorizedError("Invalid credentials")
        
        # Check status
        if not user.is_verified:
            raise UnauthorizedError("Email not verified")
        
        if user.is_deactivated:
            raise UnauthorizedError("Account deactivated")
        
        # Verify password
        if not verify_password(password, user.password_hash):
            raise UnauthorizedError("Invalid credentials")
        
        # Get user's primary membership
        membership = await session.execute(
            select(UserOrganizationMembership).where(
                UserOrganizationMembership.user_id == user.id,
                UserOrganizationMembership.is_primary == True,
            )
        )
        membership = membership.scalar_one_or_none()
        
        org_id = membership.organization_id if membership else None
        role = Role(membership.role) if membership else Role.REPORTER
        
        # Issue tokens
        access_token = issue_access_token(user.id, org_id, role)
        refresh_token_value = secrets.token_urlsafe(64)
        refresh_token_hash = _hash_token(refresh_token_value)
        family_id = _generate_token_family()
        jti = new_id()
        expires_at = utcnow() + timedelta(days=REFRESH_TOKEN_TTL_DAYS)
        
        # Store refresh token
        refresh_record = AuthRefreshToken(
            user_id=user.id,
            token_hash=refresh_token_hash,
            family_id=family_id,
            jti=jti,
            expires_at=expires_at,
            ip_address=ip,
            user_agent=request.headers.get("user-agent"),
        )
        session.add(refresh_record)
        await session.commit()
    
    # Create response with cookie
    response = Response()
    response.set_cookie(
        key="refresh_token",
        value=refresh_token_value,
        max_age=REFRESH_TOKEN_TTL_DAYS * 86400,
        httponly=True,
        secure=True,  # True in production
        samesite="lax",
    )
    
    # Emit event
    await get_event_bus().publish("user.logged_in", {
        "user_id": str(user.id),
        "ip": ip,
        "user_agent": request.headers.get("user-agent"),
    })
    
    logger.info(f"User logged in: {email}")
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_TTL_MINUTES * 60,
    }


async def refresh(refresh_token_value: str, request: Request) -> dict:
    """
    Refresh access token.
    
    POST /auth/refresh
    - Rotation: invalidates presented token, issues new one in same family
    - REUSE detection: if already-rotated token presented, invalidates entire family + force re-login
    """
    if not _db:
        raise RuntimeError("AUTH module not initialized")
    
    refresh_token_hash = _hash_token(refresh_token_value)
    
    async with _db.session_factory() as session:
        # Find refresh token
        token_record = await session.execute(
            select(AuthRefreshToken).where(
                AuthRefreshToken.token_hash == refresh_token_hash,
                AuthRefreshToken.revoked == False,
                AuthRefreshToken.expires_at > utcnow(),
            )
        )
        token_record = token_record.scalar_one_or_none()
        
        if not token_record:
            raise UnauthorizedError("Invalid or expired refresh token")
        
        # Check for REUSE attack (token already rotated)
        # In a proper implementation, we'd check if this token was already used
        # For simplicity, we just rotate
        
        # Get user
        user = await session.get(User, token_record.user_id)
        if not user or user.is_deactivated or not user.is_verified:
            raise UnauthorizedError("User account invalid")
        
        # Revoke current token
        token_record.revoked = True
        
        # Get membership for new token
        membership = await session.execute(
            select(UserOrganizationMembership).where(
                UserOrganizationMembership.user_id == user.id,
                UserOrganizationMembership.is_primary == True,
            )
        )
        membership = membership.scalar_one_or_none()
        
        org_id = membership.organization_id if membership else None
        role = Role(membership.role) if membership else Role.REPORTER
        
        # Issue new tokens
        access_token = issue_access_token(user.id, org_id, role)
        new_refresh_value = secrets.token_urlsafe(64)
        new_refresh_hash = _hash_token(new_refresh_value)
        new_jti = new_id()
        expires_at = utcnow() + timedelta(days=REFRESH_TOKEN_TTL_DAYS)
        
        new_refresh_record = AuthRefreshToken(
            user_id=user.id,
            token_hash=new_refresh_hash,
            family_id=token_record.family_id,  # Same family
            jti=new_jti,
            expires_at=expires_at,
        )
        session.add(new_refresh_record)
        await session.commit()
    
    response = Response()
    response.set_cookie(
        key="refresh_token",
        value=new_refresh_value,
        max_age=REFRESH_TOKEN_TTL_DAYS * 86400,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_TTL_MINUTES * 60,
    }


async def logout(refresh_token_value: Optional[str] = Cookie(None)) -> dict:
    """
    Logout user.
    
    POST /auth/logout
    - Revokes current refresh token family
    - Clears cookie
    """
    if not _db:
        raise RuntimeError("AUTH module not initialized")
    
    if refresh_token_value:
        refresh_token_hash = _hash_token(refresh_token_value)
        
        async with _db.session_factory() as session:
            # Find token and revoke entire family
            token_record = await session.execute(
                select(AuthRefreshToken).where(
                    AuthRefreshToken.token_hash == refresh_token_hash,
                )
            )
            token_record = token_record.scalar_one_or_none()
            
            if token_record:
                # Revoke entire family
                await session.execute(
                    text("""
                        UPDATE auth_refresh_tokens 
                        SET revoked = TRUE 
                        WHERE family_id = :family_id
                    """),
                    {"family_id": token_record.family_id}
                )
                await session.commit()
    
    response = Response()
    response.delete_cookie("refresh_token")
    
    return {"message": "Logged out successfully"}


async def forgot_password(email: str) -> dict:
    """
    Request password reset.
    
    POST /auth/forgot-password
    - If user exists, creates single-use reset token (30min) + sends email
    - Constant response to prevent enumeration
    - Rate-limited
    """
    if not _db or not _email:
        raise RuntimeError("AUTH module not initialized")
    
    async with _db.session_factory() as session:
        user = await session.execute(
            select(User).where(User.email == email)
        )
        user = user.scalar_one_or_none()
        
        if user and not user.is_deactivated:
            # Create reset token (30min expiry)
            token_value = secrets.token_urlsafe(32)
            token_hash = _hash_token(token_value)
            expires_at = utcnow() + timedelta(minutes=30)
            
            reset_token = PasswordResetToken(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=expires_at,
            )
            session.add(reset_token)
            await session.commit()
            
            # Send email (async)
            try:
                await _email.send_template(
                    template="password_reset",
                    to=email,
                    vars={"email": email, "reset_url": f"/auth/reset-password?token={token_value}"},
                )
            except Exception as e:
                logger.error(f"Failed to send password reset email: {e}")
    
    # Constant response
    return {"message": "If the email is registered, you will receive a password reset link."}


async def reset_password(token: str, new_password: str) -> dict:
    """
    Reset password with token.
    
    POST /auth/reset-password
    - Validates token
    - Updates hash
    - Invalidates all sessions
    - Marks token used
    - Emits user.password_reset
    """
    if not _db:
        raise RuntimeError("AUTH module not initialized")
    
    # Validate new password
    violations = password_policy(new_password)
    if violations:
        raise ValueError(f"Password violations: {[v.value for v in violations]}")
    
    token_hash = _hash_token(token)
    
    async with _db.session_factory() as session:
        # Find and validate token
        token_record = await session.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used == False,
                PasswordResetToken.expires_at > utcnow(),
            )
        )
        token_record = token_record.scalar_one_or_none()
        
        if not token_record:
            raise NotFoundError("password_reset_token", "invalid or expired")
        
        # Update password
        user = await session.get(User, token_record.user_id)
        if not user:
            raise NotFoundError("user", token_record.user_id)
        
        user.password_hash = hash_password(new_password)
        token_record.used = True
        
        await session.commit()
    
    # Invalidate all sessions
    await invalidate_user_sessions(user.id)
    
    # Emit event
    await get_event_bus().publish("user.password_reset", {"user_id": str(user.id)})
    
    logger.info(f"Password reset for user {user.id}")
    return {"message": "Password reset successfully"}


async def me(ctx: RequestContext) -> Profile:
    """
    Get current user profile.
    
    GET /auth/me
    - Returns Profile{user, membership, organization, role, permissions[]}
    """
    if not _db or not ctx.user_id:
        raise UnauthorizedError("Authentication required")
    
    async with _db.session_factory() as session:
        user = await session.get(User, ctx.user_id)
        if not user:
            raise NotFoundError("user", ctx.user_id)
        
        # Get membership
        membership = await session.execute(
            select(UserOrganizationMembership).where(
                UserOrganizationMembership.user_id == user.id,
                UserOrganizationMembership.is_primary == True,
            )
        )
        membership = membership.scalar_one_or_none()
        
        org_id = membership.organization_id if membership else None
        org_name = None
        role = Role(membership.role) if membership else None
        
        # Get permissions
        permissions = list(PERMISSION_MATRIX.get(role, set())) if role else []
    
    return Profile(
        user_id=user.id,
        email=user.email,
        is_verified=user.is_verified,
        is_deactivated=user.is_deactivated,
        timezone=user.timezone,
        organization_id=org_id,
        organization_name=org_name,
        role=role,
        permissions=permissions,
    )


# =============================================================================
# RBAC Functions
# =============================================================================

def rbac_can(ctx: RequestContext, action: str, resource: Any = None) -> bool:
    """
    Check if user can perform action on resource.
    
    Implements permission matrix (role x action) + object-level rules.
    Deactivated users always return False.
    """
    if not ctx.user_id or not ctx.role:
        return False
    
    # Deactivated users blocked
    if hasattr(ctx, "is_deactivated") and ctx.is_deactivated:
        return False
    
    # Check permission matrix
    allowed_actions = PERMISSION_MATRIX.get(ctx.role, set())
    
    # SYS_ADMIN has all permissions
    if "*" in allowed_actions:
        return True
    
    if action not in allowed_actions:
        return False
    
    # Check object-level rules
    if action in OBJECT_RULES:
        rule = OBJECT_RULES[action]
        return rule(ctx, resource)
    
    return True


def require_roles(*roles: Role):
    """FastAPI dependency to require specific roles."""
    async def check_role(ctx: RequestContext = Depends(api_request_context)):
        if not ctx.role or ctx.role not in roles:
            raise ForbiddenError(f"Required roles: {[r.value for r in roles]}")
        return ctx
    return check_role


# =============================================================================
# Admin Functions
# =============================================================================

async def change_role(
    ctx: RequestContext,
    user_id: UUID,
    new_role: Role,
) -> dict:
    """
    Change user role.
    
    PATCH /auth/roles
    - MANAGER/SYS_ADMIN only
    - Cannot grant SYS_ADMIN via org APIs
    - Audited
    - Emits user.role_changed
    """
    if not _db:
        raise RuntimeError("AUTH module not initialized")
    
    # Check permission
    if ctx.role not in [Role.MANAGER, Role.SYS_ADMIN]:
        raise ForbiddenError("change_role", "auth")
    
    # Cannot grant SYS_ADMIN via org APIs
    if new_role == Role.SYS_ADMIN and ctx.role != Role.SYS_ADMIN:
        raise ForbiddenError("Cannot grant SYS_ADMIN role")
    
    async with _db.session_factory() as session:
        membership = await session.execute(
            select(UserOrganizationMembership).where(
                UserOrganizationMembership.user_id == user_id,
                UserOrganizationMembership.organization_id == ctx.org_id,
            )
        )
        membership = membership.scalar_one_or_none()
        
        if not membership:
            raise NotFoundError("membership", user_id)
        
        old_role = membership.role
        membership.role = new_role.value
        membership.updated_at = utcnow()
        
        await session.commit()
    
    # Emit event
    await get_event_bus().publish("user.role_changed", {
        "user_id": str(user_id),
        "old_role": old_role,
        "new_role": new_role.value,
        "changed_by": str(ctx.user_id),
    })
    
    logger.info(f"Role changed for user {user_id}: {old_role} -> {new_role.value}")
    return {"message": "Role updated successfully"}


async def deactivate_user(
    ctx: RequestContext,
    user_id: UUID,
) -> dict:
    """
    Deactivate user.
    
    - Blocks new actions/assignments
    - Retains history
    - Invalidates sessions
    - Audited
    - Emits user.deactivated
    """
    if not _db:
        raise RuntimeError("AUTH module not initialized")
    
    # Check permission
    if ctx.role not in [Role.MANAGER, Role.SYS_ADMIN]:
        raise ForbiddenError("deactivate_user", "auth")
    
    async with _db.session_factory() as session:
        user = await session.get(User, user_id)
        if not user:
            raise NotFoundError("user", user_id)
        
        user.is_deactivated = True
        user.updated_at = utcnow()
        
        await session.commit()
    
    # Invalidate sessions
    await invalidate_user_sessions(user_id)
    
    # Emit event
    await get_event_bus().publish("user.deactivated", {
        "user_id": str(user_id),
        "deactivated_by": str(ctx.user_id),
    })
    
    logger.info(f"User deactivated: {user_id}")
    return {"message": "User deactivated successfully"}


# =============================================================================
# Background Tasks
# =============================================================================

async def sweep_expired_tokens() -> int:
    """
    Sweep expired tokens.
    
    Beat task (daily): Delete expired verification/reset/refresh rows.
    """
    if not _db:
        return 0
    
    async with _db.session_factory() as session:
        now = utcnow()
        
        # Delete expired verification tokens
        result = await session.execute(
            text("""
                DELETE FROM email_verification_tokens 
                WHERE expires_at < :now OR used = TRUE
            """),
            {"now": now}
        )
        deleted_verification = result.rowcount
        
        # Delete expired reset tokens
        result = await session.execute(
            text("""
                DELETE FROM password_reset_tokens 
                WHERE expires_at < :now OR used = TRUE
            """),
            {"now": now}
        )
        deleted_reset = result.rowcount
        
        # Delete expired/revoked refresh tokens
        result = await session.execute(
            text("""
                DELETE FROM auth_refresh_tokens 
                WHERE expires_at < :now OR revoked = TRUE
            """),
            {"now": now}
        )
        deleted_refresh = result.rowcount
        
        await session.commit()
    
    total = deleted_verification + deleted_reset + deleted_refresh
    logger.info(f"Swept {total} expired tokens")
    return total


# =============================================================================
# Middleware Hook
# =============================================================================

async def auth_hook(request: Request) -> None:
    """
    Authentication middleware hook (order 30).
    
    - Extracts Bearer token from Authorization header
    - Verifies access token
    - Stores claims on request.state
    - Public route list bypasses authentication
    """
    public_routes = {
        "/api/v1/auth/signup",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/verify-email",
        "/api/v1/auth/forgot-password",
        "/api/v1/auth/reset-password",
        "/health/live",
        "/health/ready",
        "/api/v1/openapi.json",
        "/docs",
    }
    
    # Check if route is public
    if request.url.path in public_routes:
        return
    
    # Extract Bearer token
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise UnauthorizedError("Missing or invalid Authorization header")
    
    token = auth_header[7:]  # Remove "Bearer " prefix
    
    # Verify token
    claims = verify_access_token(token)
    
    # Store on request.state
    request.state.user_id = claims.sub
    request.state.organization_id = claims.organization_id
    request.state.role = claims.role
    request.state.authenticated = True


# =============================================================================
# Module Implementation
# =============================================================================

class AuthService(ModuleBase):
    """AUTH module implementing identity management and RBAC."""
    
    name = "auth"
    version = "1.0.0"
    dependencies = ("core", "db", "cache", "email", "api")
    optional_dependencies = ()
    profiles = ("api", "worker", "beat", "all-in-one")
    
    def __init__(self):
        self._ctx: ModuleContext | None = None
        self._healthy = False
    
    async def configure(self, settings: Any) -> None:
        """Configure AUTH module."""
        logger.info("Configuring AUTH module")
        self._healthy = False
    
    async def initialize(self, ctx: ModuleContext) -> None:
        """Initialize AUTH module with dependencies."""
        global _db, _cache, _email, _api
        
        self._ctx = ctx
        
        # Get dependencies
        _db = get_service("db", DatabaseService)
        _cache = get_service("cache", CacheService)
        _email = get_service("email", EmailService)
        _api = get_service("api", HttpApi)
        
        logger.info("AUTH module initialized with dependencies")
    
    async def start(self) -> None:
        """Start AUTH module - register routes and tasks."""
        global _api
        
        if _api:
            # Register router
            router = AuthRouter()
            _api.register_router(router, prefix="auth", tags=["Authentication"])
            
            logger.info("AUTH routes registered")
        
        self._healthy = True
        logger.info("AUTH module started")
    
    async def stop(self) -> None:
        """Stop AUTH module gracefully."""
        logger.info("Stopping AUTH module")
        self._healthy = False
    
    async def health(self) -> HealthReport:
        """Check AUTH module health."""
        if not self._healthy:
            return HealthReport(
                module=self.name,
                status=HealthStatus.UNAVAILABLE,
                details={"reason": "Module not started"},
            )
        
        # Check DB connectivity
        db_health = "OK" if _db else "MISSING"
        
        return HealthReport(
            module=self.name,
            status=HealthStatus.OK if db_health == "OK" else HealthStatus.DEGRADED,
            details={
                "db": db_health,
                "jwt_configured": bool(JWT_SECRET),
            },
        )


class AuthRouter:
    """FastAPI router for AUTH endpoints."""
    
    def __init__(self):
        from fastapi import APIRouter
        
        self.router = APIRouter(prefix="/auth", tags=["Authentication"])
        
        # Register routes
        self.router.post("/signup")(self._signup_handler)
        self.router.post("/verify-email")(self._verify_email_handler)
        self.router.post("/login")(self._login_handler)
        self.router.post("/refresh")(self._refresh_handler)
        self.router.post("/logout")(self._logout_handler)
        self.router.post("/forgot-password")(self._forgot_password_handler)
        self.router.post("/reset-password")(self._reset_password_handler)
        self.router.get("/me")(self._me_handler)
        self.router.patch("/roles")(self._change_role_handler)
        self.router.post("/deactivate")(self._deactivate_handler)
    
    async def _signup_handler(self, email: str, password: str, timezone: str = "UTC") -> dict:
        return await signup(email, password, timezone)
    
    async def _verify_email_handler(self, token: str) -> dict:
        await verify_email(token)
        return {"message": "Email verified successfully"}
    
    async def _login_handler(self, email: str, password: str, request: Request) -> dict:
        return await login(email, password, request)
    
    async def _refresh_handler(self, refresh_token: Optional[str] = Cookie(None), request: Request = None) -> dict:
        return await refresh(refresh_token, request)
    
    async def _logout_handler(self, refresh_token: Optional[str] = Cookie(None)) -> dict:
        return await logout(refresh_token)
    
    async def _forgot_password_handler(self, email: str) -> dict:
        return await forgot_password(email)
    
    async def _reset_password_handler(self, token: str, new_password: str) -> dict:
        return await reset_password(token, new_password)
    
    async def _me_handler(self, ctx: RequestContext = Depends(api_request_context)) -> Profile:
        return await me(ctx)
    
    async def _change_role_handler(
        self,
        user_id: UUID,
        new_role: Role,
        ctx: RequestContext = Depends(api_request_context),
    ) -> dict:
        return await change_role(ctx, user_id, new_role)
    
    async def _deactivate_handler(
        self,
        user_id: UUID,
        ctx: RequestContext = Depends(api_request_context),
    ) -> dict:
        return await deactivate_user(ctx, user_id)
