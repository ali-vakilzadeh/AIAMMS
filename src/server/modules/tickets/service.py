"""
TICKETS and FILES Module Service Implementation

Implements:
- TICKETS: Repair ticket lifecycle with payment gate, pool routing, 5-step flow, loop cap, escalation
- FILES: File attachment domain with policy validation, ingestion flagging for AI
"""

import asyncio
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Literal, Set, Tuple
from uuid import UUID, uuid4
import hashlib

from pydantic import BaseModel, Field
from sqlalchemy import select, func, text as sql_text, Index, UniqueConstraint, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File as FastAPIFile
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import ForeignKey

from ...shared.types import (
    RequestContext,
    Role,
    DomainError,
    NotFoundError,
    ForbiddenError,
    QuotaExceededError,
    InvalidTransitionError,
    Page as PageType,
)
from ...core.event_bus import get_event_bus
from ...core.module_base import ModuleBase, ModuleContext, HealthStatus
from ...core.registry import get_service
from ...core.logger import get_logger
from ...core.utils import utcnow, new_id
from ...core.health import HealthReport

logger = get_logger(__name__)


async def publish(event: str, payload: dict, post_commit: bool = False) -> None:
    """Publish an event to the event bus."""
    event_bus = get_event_bus()
    await event_bus.publish(event, payload, post_commit)


# ============================================================================
# Enums
# ============================================================================

class TicketStatus(str, Enum):
    """Ticket state machine states."""
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    REPORT_SUBMITTED = "REPORT_SUBMITTED"
    ISSUER_FEEDBACK_REQUIRED = "ISSUER_FEEDBACK_REQUIRED"
    ISSUER_ACCEPTED = "ISSUER_ACCEPTED"
    CLOSED = "CLOSED"
    ESCALATED_TO_MANAGER = "ESCALATED_TO_MANAGER"


class TicketPriority(str, Enum):
    """Ticket priority levels."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FilePurpose(str, Enum):
    """File upload purposes."""
    ATTACHMENT = "ATTACHMENT"
    MANUAL = "MANUAL"
    PHOTO = "PHOTO"
    EXPORT = "EXPORT"
    AI_INGESTION_ARTIFACT = "AI_INGESTION_ARTIFACT"


class IngestionStatus(str, Enum):
    """AI ingestion processing status."""
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DupDecisionAction(str, Enum):
    """Duplicate file handling actions."""
    REJECT = "REJECT"
    VERSION = "VERSION"
    ALLOW = "ALLOW"


# ============================================================================
# Data Models (Pydantic)
# ============================================================================

class TicketCreate(BaseModel):
    """Request to create a repair ticket."""
    service_point_id: UUID
    report_section: Optional[str] = None
    description: str = Field(..., min_length=1)
    priority: TicketPriority = TicketPriority.MEDIUM
    attachments: Optional[List[UUID]] = None  # File IDs to attach


class ClaimRequest(BaseModel):
    """Request to claim a ticket."""
    pass


class AssignRequest(BaseModel):
    """Request to assign a ticket."""
    user_id: UUID


class ReportSubmit(BaseModel):
    """Request to submit maintenance report."""
    work_performed: str
    findings: Optional[str] = None
    attachments: Optional[List[UUID]] = None  # File IDs


class FeedbackSubmit(BaseModel):
    """Request to submit issuer feedback."""
    feedback: str
    accept_report: bool = False  # If True, skip to accept


class EscalateRequest(BaseModel):
    """Request to escalate a ticket."""
    reason: Optional[str] = None


class ManagerDecision(BaseModel):
    """Manager decision on escalated ticket."""
    decision: Literal["FORCE_CLOSE", "REQUIRE_NEW_TICKET", "MANDATE_ACTION"]
    note: str


class TicketView(BaseModel):
    """Ticket summary view."""
    id: UUID
    code: str
    service_point_id: UUID
    service_point_name: Optional[str]
    status: TicketStatus
    priority: TicketPriority
    description: str
    created_at: datetime
    created_by: UUID
    assigned_to: Optional[UUID]
    loop_counter: int
    has_escalation: bool


class TicketDetail(BaseModel):
    """Full ticket detail with history."""
    id: UUID
    code: str
    organization_id: UUID
    service_point_id: UUID
    service_point_name: Optional[str]
    status: TicketStatus
    priority: TicketPriority
    description: str
    report_section: Optional[str]
    created_at: datetime
    created_by: UUID
    assigned_to: Optional[UUID]
    loop_counter: int
    reports: List[Dict[str, Any]]
    feedbacks: List[Dict[str, Any]]
    assignments: List[Dict[str, Any]]
    events: List[Dict[str, Any]]
    attachments: List[Dict[str, Any]]


class FileUploadMeta(BaseModel):
    """File metadata for upload."""
    original_name: str
    mime: str
    size: int
    purpose: FilePurpose = FilePurpose.ATTACHMENT
    entity_type: Optional[str] = None
    entity_id: Optional[UUID] = None


class FileView(BaseModel):
    """File metadata view."""
    id: UUID
    original_name: str
    key: str
    mime: str
    size: int
    uploaded_by: UUID
    entity_type: Optional[str]
    entity_id: Optional[UUID]
    purpose: FilePurpose
    ingestion_status: Optional[IngestionStatus]
    uploaded_at: datetime


class DupDecision(BaseModel):
    """Duplicate file handling decision."""
    action: DupDecisionAction
    reason: Optional[str] = None


# ============================================================================
# SQLAlchemy Models
# ============================================================================

class Base(DeclarativeBase):
    pass


class Ticket(Base):
    __tablename__ = "tickets"
    
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(index=True, nullable=False)
    code: Mapped[str] = mapped_column(unique=True, index=True, nullable=False)
    service_point_id: Mapped[UUID] = mapped_column(index=True, nullable=False)
    status: Mapped[str] = mapped_column(default="OPEN")
    priority: Mapped[str] = mapped_column(default="MEDIUM")
    description: Mapped[str]
    report_section: Mapped[Optional[str]]
    created_at: Mapped[datetime] = mapped_column(default=lambda: utcnow())
    created_by: Mapped[UUID] = mapped_column(index=True)
    assigned_to: Mapped[Optional[UUID]] = mapped_column(index=True)
    loop_counter: Mapped[int] = mapped_column(default=0)
    escalated_at: Mapped[Optional[datetime]]
    escalated_by: Mapped[Optional[UUID]]
    closed_at: Mapped[Optional[datetime]]
    deleted_at: Mapped[Optional[datetime]]
    
    # Relationships
    reports: Mapped[List["TicketReport"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan"
    )
    feedbacks: Mapped[List["TicketFeedback"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan"
    )
    assignments: Mapped[List["TicketAssignment"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan"
    )
    events: Mapped[List["TicketEvent"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan"
    )
    
    __table_args__ = (
        Index("ix_tickets_org_status", "organization_id", "status"),
        Index("ix_tickets_service_point", "service_point_id"),
        Index("ix_tickets_created", "created_at"),
    )


class TicketReport(Base):
    __tablename__ = "ticket_reports"
    
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: new_id())
    ticket_id: Mapped[UUID] = mapped_column(ForeignKey("tickets.id"), index=True, nullable=False)
    work_performed: Mapped[str]
    findings: Mapped[Optional[str]]
    submitted_at: Mapped[datetime] = mapped_column(default=lambda: utcnow())
    submitted_by: Mapped[UUID]
    
    ticket: Mapped["Ticket"] = relationship(back_populates="reports")


class TicketFeedback(Base):
    __tablename__ = "ticket_feedbacks"
    
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: new_id())
    ticket_id: Mapped[UUID] = mapped_column(ForeignKey("tickets.id"), index=True, nullable=False)
    feedback: Mapped[str]
    accept_report: Mapped[bool] = mapped_column(default=False)
    submitted_at: Mapped[datetime] = mapped_column(default=lambda: utcnow())
    submitted_by: Mapped[UUID]
    
    ticket: Mapped["Ticket"] = relationship(back_populates="feedbacks")


class TicketAssignment(Base):
    __tablename__ = "ticket_assignments"
    
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: new_id())
    ticket_id: Mapped[UUID] = mapped_column(ForeignKey("tickets.id"), index=True, nullable=False)
    assigned_to: Mapped[UUID]
    assigned_at: Mapped[datetime] = mapped_column(default=lambda: utcnow())
    assigned_by: Mapped[UUID]
    assignment_type: Mapped[str]  # CLAIM|MANUAL_ASSIGN|REASSIGN
    
    ticket: Mapped["Ticket"] = relationship(back_populates="assignments")


class TicketEvent(Base):
    __tablename__ = "ticket_events"
    
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: new_id())
    ticket_id: Mapped[UUID] = mapped_column(ForeignKey("tickets.id"), index=True, nullable=False)
    event_type: Mapped[str]
    event_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(default=lambda: utcnow())
    actor_id: Mapped[UUID]
    
    ticket: Mapped["Ticket"] = relationship(back_populates="events")


class File(Base):
    __tablename__ = "files"
    
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(index=True, nullable=False)
    original_name: Mapped[str]
    key: Mapped[str] = mapped_column(index=True, unique=True)  # STORAGE tenant key
    mime: Mapped[str]
    size: Mapped[int]
    content_hash: Mapped[Optional[str]] = mapped_column(index=True)  # For duplicate detection
    uploaded_by: Mapped[UUID] = mapped_column(index=True)
    uploaded_at: Mapped[datetime] = mapped_column(default=lambda: utcnow())
    entity_type: Mapped[Optional[str]]  # SERVICE_POINT|WORK_ORDER|WORK_ORDER_ITEM|TICKET
    entity_id: Mapped[Optional[UUID]]
    purpose: Mapped[str] = mapped_column(default="ATTACHMENT")
    ingestion_status: Mapped[Optional[str]]
    ingestion_job_id: Mapped[Optional[str]]
    deleted_at: Mapped[Optional[datetime]]
    
    __table_args__ = (
        Index("ix_files_org_entity", "organization_id", "entity_type", "entity_id"),
        Index("ix_files_purpose", "purpose"),
    )


# ============================================================================
# Services
# ============================================================================

class TicketService:
    """Service for ticket operations."""
    
    def __init__(self, db_session: AsyncSession, ctx: RequestContext):
        self.db = db_session
        self.ctx = ctx
    
    async def _record_event(self, ticket_id: UUID, event_type: str, data: Optional[Dict] = None) -> None:
        """Record a ticket event."""
        event = TicketEvent(
            ticket_id=ticket_id,
            event_type=event_type,
            event_data=data,
            actor_id=self.ctx.user_id,
        )
        self.db.add(event)
        await self.db.flush()
    
    async def _get_ticket(self, ticket_id: UUID) -> Ticket:
        """Get ticket with org check."""
        stmt = select(Ticket).where(
            Ticket.id == ticket_id,
            Ticket.organization_id == self.ctx.org_id,
            Ticket.deleted_at.is_(None),
        )
        result = await self.db.execute(stmt)
        ticket = result.scalar_one_or_none()
        if not ticket:
            raise NotFoundError(f"Ticket {ticket_id} not found")
        return ticket
    
    async def create_ticket(self, data: TicketCreate) -> Ticket:
        """
        Create a repair ticket.
        
        Gate 1: TENANCY.can_create_ticket (payment state check)
        Gate 2: Node must be ACTIVE (unless domain rule allows)
        Routes to Maintenance Pool by default
        """
        # Gate 1: Payment check via TENANCY
        tenancy = get_service("tenancy", "TenancyService")
        if tenancy:
            can_create = await tenancy.can_create_ticket(self.ctx.org_id)
            if not can_create:
                raise ForbiddenError(
                    error_code="ORG_PAYMENT_OVERDUE",
                    message="Organization payment is overdue. Cannot create new tickets."
                )
        
        # Gate 2: Check service point status via ASSETS
        assets = get_service("assets", "AssetQuery")
        node_active = True
        if assets:
            try:
                node_info = await assets.get_node(data.service_point_id)
                node_active = node_info.get("status") == "ACTIVE"
            except Exception:
                node_active = False
        
        if not node_active:
            # Allow only if domain rule permits (e.g., safety issue)
            # For MVP, reject inactive nodes
            raise ForbiddenError(
                error_code="NODE_NOT_ACTIVE",
                message="Cannot create ticket for inactive service point."
            )
        
        # Create ticket
        ticket = Ticket(
            organization_id=self.ctx.org_id,
            code=f"TCK-{new_id()[:8].upper()}",
            service_point_id=data.service_point_id,
            status="OPEN",
            priority=data.priority.value,
            description=data.description,
            report_section=data.report_section,
            created_by=self.ctx.user_id,
        )
        self.db.add(ticket)
        await self.db.flush()
        
        # Record creation event
        await self._record_event(
            ticket.id,
            "CREATED",
            {"priority": data.priority.value, "service_point_id": str(data.service_point_id)},
        )
        
        # Attach files if provided
        if data.attachments:
            file_service = get_service("files", "FileService")
            if file_service:
                for file_id in data.attachments:
                    await file_service.attach(
                        entity_type="TICKET",
                        entity_id=ticket.id,
                        file_id=file_id,
                    )
        
        await self.db.commit()
        
        # Emit event
        await publish("ticket.created", {
            "ticket_id": str(ticket.id),
            "organization_id": str(self.ctx.org_id),
            "service_point_id": str(data.service_point_id),
            "priority": data.priority.value,
            "created_by": str(self.ctx.user_id),
        })
        
        # Notify maintenance role
        notify = get_service("notify", "NotifyService")
        if notify:
            await notify.notify_role(
                org_id=self.ctx.org_id,
                role=Role.MAINTENANCE,
                event="ticket.created",
                data={"ticket_id": str(ticket.id), "code": ticket.code},
            )
        
        logger.info(f"Ticket created: {ticket.id}")
        return ticket
    
    async def list_tickets(self, filters: Optional[Dict] = None, page: int = 1, page_size: int = 50) -> PageType:
        """List tickets with org+role scoping."""
        # Build query
        stmt = select(Ticket).where(
            Ticket.organization_id == self.ctx.org_id,
            Ticket.deleted_at.is_(None),
        )
        
        # Role filtering
        if self.ctx.role in [Role.OPERATOR]:
            # Operators see only tickets they created
            stmt = stmt.where(Ticket.created_by == self.ctx.user_id)
        elif self.ctx.role in [Role.MAINTENANCE]:
            # Maintenance sees assigned tickets + unassigned pool
            stmt = stmt.where(
                or_(
                    Ticket.assigned_to == self.ctx.user_id,
                    Ticket.assigned_to.is_(None),
                )
            )
        # MANAGER/SYS_ADMIN see all (no filter)
        
        # Apply filters
        if filters:
            if "status" in filters:
                stmt = stmt.where(Ticket.status == filters["status"])
            if "priority" in filters:
                stmt = stmt.where(Ticket.priority == filters["priority"])
            if "service_point_id" in filters:
                stmt = stmt.where(Ticket.service_point_id == filters["service_point_id"])
        
        # Pagination
        total_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await self.db.execute(total_stmt)
        total = total_result.scalar() or 0
        
        offset = (page - 1) * page_size
        stmt = stmt.order_by(Ticket.created_at.desc()).offset(offset).limit(page_size)
        
        result = await self.db.execute(stmt)
        tickets = result.scalars().all()
        
        items = [
            TicketView(
                id=t.id,
                code=t.code,
                service_point_id=t.service_point_id,
                service_point_name=None,  # Would join with ASSETS
                status=TicketStatus(t.status),
                priority=TicketPriority(t.priority),
                description=t.description,
                created_at=t.created_at,
                created_by=t.created_by,
                assigned_to=t.assigned_to,
                loop_counter=t.loop_counter,
                has_escalation=t.escalated_at is not None,
            )
            for t in tickets
        ]
        
        return Page(items=items, total=total, page=page, page_size=page_size)
    
    async def get_ticket(self, ticket_id: UUID) -> TicketDetail:
        """Get full ticket detail."""
        ticket = await self._get_ticket(ticket_id)
        
        # Load related data
        reports_stmt = select(TicketReport).where(TicketReport.ticket_id == ticket_id)
        reports_result = await self.db.execute(reports_stmt)
        reports = [{"id": r.id, "work_performed": r.work_performed, "findings": r.findings, "submitted_at": r.submitted_at, "submitted_by": r.submitted_by} for r in reports_result.scalars().all()]
        
        feedbacks_stmt = select(TicketFeedback).where(TicketFeedback.ticket_id == ticket_id)
        feedbacks_result = await self.db.execute(feedbacks_stmt)
        feedbacks = [{"id": f.id, "feedback": f.feedback, "accept_report": f.accept_report, "submitted_at": f.submitted_at, "submitted_by": f.submitted_by} for f in feedbacks_result.scalars().all()]
        
        assignments_stmt = select(TicketAssignment).where(TicketAssignment.ticket_id == ticket_id).order_by(TicketAssignment.assigned_at.desc())
        assignments_result = await self.db.execute(assignments_stmt)
        assignments = [{"id": a.id, "assigned_to": a.assigned_to, "assigned_at": a.assigned_at, "assigned_by": a.assigned_by, "assignment_type": a.assignment_type} for a in assignments_result.scalars().all()]
        
        events_stmt = select(TicketEvent).where(TicketEvent.ticket_id == ticket_id).order_by(TicketEvent.occurred_at.desc())
        events_result = await self.db.execute(events_stmt)
        events = [{"id": e.id, "event_type": e.event_type, "event_data": e.event_data, "occurred_at": e.occurred_at, "actor_id": e.actor_id} for e in events_result.scalars().all()]
        
        # Get attachments via FILES
        attachments = []
        file_service = get_service("files", "FileService")
        if file_service:
            attachments = await file_service.list_for_entity("TICKET", ticket_id)
        
        return TicketDetail(
            id=ticket.id,
            code=ticket.code,
            organization_id=ticket.organization_id,
            service_point_id=ticket.service_point_id,
            service_point_name=None,  # Would join with ASSETS
            status=TicketStatus(ticket.status),
            priority=TicketPriority(ticket.priority),
            description=ticket.description,
            report_section=ticket.report_section,
            created_at=ticket.created_at,
            created_by=ticket.created_by,
            assigned_to=ticket.assigned_to,
            loop_counter=ticket.loop_counter,
            reports=reports,
            feedbacks=feedbacks,
            assignments=assignments,
            events=events,
            attachments=attachments,
        )
    
    async def claim(self, ticket_id: UUID) -> Ticket:
        """
        Claim a ticket (MAINTENANCE role).
        OPEN -> IN_PROGRESS
        """
        ticket = await self._get_ticket(ticket_id)
        
        # Validate transition
        if ticket.status != "OPEN":
            raise InvalidTransitionError(f"Cannot claim ticket in status {ticket.status}")
        
        # Check role
        if self.ctx.role not in [Role.MAINTENANCE, Role.MANAGER, Role.SYS_ADMIN]:
            raise ForbiddenError("Only MAINTENANCE can claim tickets")
        
        # Update status
        ticket.status = "IN_PROGRESS"
        ticket.assigned_to = self.ctx.user_id
        
        # Record assignment
        assignment = TicketAssignment(
            ticket_id=ticket.id,
            assigned_to=self.ctx.user_id,
            assigned_by=self.ctx.user_id,
            assignment_type="CLAIM",
        )
        self.db.add(assignment)
        
        # Record event
        await self._record_event(ticket.id, "CLAIMED", {"claimed_by": str(self.ctx.user_id)})
        
        await self.db.commit()
        
        # Emit event
        await publish("ticket.claimed", {
            "ticket_id": str(ticket.id),
            "claimed_by": str(self.ctx.user_id),
        })
        
        # Notify issuer
        notify = get_service("notify", "NotifyService")
        if notify:
            await notify.notify_user(
                user_id=ticket.created_by,
                event="ticket.claimed",
                data={"ticket_id": str(ticket.id), "code": ticket.code, "claimed_by": str(self.ctx.user_id)},
            )
        
        logger.info(f"Ticket claimed: {ticket.id} by {self.ctx.user_id}")
        return ticket
    
    async def assign(self, ticket_id: UUID, user_id: UUID) -> Ticket:
        """
        Assign a ticket (MANAGER role).
        Manual assignment or reassignment.
        """
        ticket = await self._get_ticket(ticket_id)
        
        # Check role
        if self.ctx.role not in [Role.MANAGER, Role.SYS_ADMIN]:
            raise ForbiddenError("Only MANAGER can assign tickets")
        
        # Update assignment
        was_assigned = ticket.assigned_to is not None
        ticket.assigned_to = user_id
        
        # Record assignment
        assignment = TicketAssignment(
            ticket_id=ticket.id,
            assigned_to=user_id,
            assigned_by=self.ctx.user_id,
            assignment_type="MANUAL_ASSIGN" if not was_assigned else "REASSIGN",
        )
        self.db.add(assignment)
        
        # Record event
        await self._record_event(ticket.id, "ASSIGNED", {"assigned_to": str(user_id), "previous": str(ticket.assigned_to) if was_assigned else None})
        
        await self.db.commit()
        
        # Emit event
        await publish("ticket.assigned", {
            "ticket_id": str(ticket.id),
            "assigned_to": str(user_id),
            "assigned_by": str(self.ctx.user_id),
        })
        
        # Notify assignee
        notify = get_service("notify", "NotifyService")
        if notify:
            await notify.notify_user(
                user_id=user_id,
                event="ticket.assigned",
                data={"ticket_id": str(ticket.id), "code": ticket.code},
            )
        
        logger.info(f"Ticket assigned: {ticket.id} to {user_id}")
        return ticket
    
    async def submit_report(self, ticket_id: UUID, data: ReportSubmit) -> Ticket:
        """
        Submit maintenance report (MAINTENANCE role).
        IN_PROGRESS -> REPORT_SUBMITTED
        """
        ticket = await self._get_ticket(ticket_id)
        
        # Validate transition
        if ticket.status != "IN_PROGRESS":
            raise InvalidTransitionError(f"Cannot submit report from status {ticket.status}")
        
        # Check role
        if self.ctx.role not in [Role.MAINTENANCE, Role.MANAGER, Role.SYS_ADMIN]:
            raise ForbiddenError("Only MAINTENANCE can submit reports")
        
        # Update status
        ticket.status = "REPORT_SUBMITTED"
        
        # Create report
        report = TicketReport(
            ticket_id=ticket.id,
            work_performed=data.work_performed,
            findings=data.findings,
            submitted_by=self.ctx.user_id,
        )
        self.db.add(report)
        
        # Attach files if provided
        if data.attachments:
            file_service = get_service("files", "FileService")
            if file_service:
                for file_id in data.attachments:
                    await file_service.attach(
                        entity_type="TICKET",
                        entity_id=ticket.id,
                        file_id=file_id,
                    )
        
        # Record event
        await self._record_event(ticket.id, "REPORT_SUBMITTED", {"report_id": report.id})
        
        await self.db.commit()
        
        # Emit event
        await publish("ticket.report_submitted", {
            "ticket_id": str(ticket.id),
            "report_id": report.id,
        })
        
        # Notify issuer
        notify = get_service("notify", "NotifyService")
        if notify:
            await notify.notify_user(
                user_id=ticket.created_by,
                event="ticket.report_submitted",
                data={"ticket_id": str(ticket.id), "code": ticket.code},
            )
        
        logger.info(f"Report submitted for ticket: {ticket.id}")
        return ticket
    
    async def submit_feedback(self, ticket_id: UUID, data: FeedbackSubmit) -> Ticket:
        """
        Submit issuer feedback.
        REPORT_SUBMITTED -> ISSUER_FEEDBACK_REQUIRED -> back to IN_PROGRESS
        Loop counter capped at 3, then auto-escalate.
        """
        ticket = await self._get_ticket(ticket_id)
        
        # Validate transition
        if ticket.status not in ["REPORT_SUBMITTED", "ISSUER_FEEDBACK_REQUIRED"]:
            raise InvalidTransitionError(f"Cannot submit feedback from status {ticket.status}")
        
        # Check role - issuer or manager
        if self.ctx.user_id != ticket.created_by and self.ctx.role not in [Role.MANAGER, Role.SYS_ADMIN]:
            raise ForbiddenError("Only issuer or MANAGER can submit feedback")
        
        # Create feedback
        feedback = TicketFeedback(
            ticket_id=ticket.id,
            feedback=data.feedback,
            accept_report=data.accept_report,
            submitted_by=self.ctx.user_id,
        )
        self.db.add(feedback)
        
        # Increment loop counter
        ticket.loop_counter += 1
        
        # Check loop cap
        if ticket.loop_counter > 3:
            # Auto-escalate
            ticket.status = "ESCALATED_TO_MANAGER"
            ticket.escalated_at = utcnow()
            ticket.escalated_by = self.ctx.user_id
            
            # Record event
            await self._record_event(ticket.id, "AUTO_ESCALATED", {"loop_counter": ticket.loop_counter, "reason": "Feedback loop exceeded 3 iterations"})
            
            await self.db.commit()
            
            # Emit events
            await publish("ticket.feedback_requested", {
                "ticket_id": str(ticket.id),
                "feedback_id": feedback.id,
            })
            await publish("ticket.escalated", {
                "ticket_id": str(ticket.id),
                "escalated_by": str(self.ctx.user_id),
                "auto": True,
            })
            
            # Notify managers
            notify = get_service("notify", "NotifyService")
            if notify:
                await notify.notify_role(
                    org_id=self.ctx.org_id,
                    role=Role.MANAGER,
                    event="ticket.escalated",
                    data={"ticket_id": str(ticket.id), "code": ticket.code, "auto": True},
                )
            
            logger.info(f"Ticket auto-escalated due to loop cap: {ticket.id}")
            return ticket
        
        # Normal flow
        if data.accept_report:
            # Skip to accepted
            ticket.status = "ISSUER_ACCEPTED"
        else:
            ticket.status = "ISSUER_FEEDBACK_REQUIRED"
        
        # Record event
        await self._record_event(ticket.id, "FEEDBACK_REQUESTED", {"feedback_id": feedback.id, "accept": data.accept_report})
        
        await self.db.commit()
        
        # Emit event
        await publish("ticket.feedback_requested", {
            "ticket_id": str(ticket.id),
            "feedback_id": feedback.id,
            "accept": data.accept_report,
        })
        
        # Notify maintenance
        notify = get_service("notify", "NotifyService")
        if notify and ticket.assigned_to:
            await notify.notify_user(
                user_id=ticket.assigned_to,
                event="ticket.feedback_requested",
                data={"ticket_id": str(ticket.id), "code": ticket.code},
            )
        
        logger.info(f"Feedback submitted for ticket: {ticket.id}")
        return ticket
    
    async def accept_ticket(self, ticket_id: UUID) -> Ticket:
        """
        Accept ticket (issuer).
        ISSUER_ACCEPTED -> CLOSED
        """
        ticket = await self._get_ticket(ticket_id)
        
        # Validate transition
        if ticket.status != "ISSUER_ACCEPTED":
            raise InvalidTransitionError(f"Cannot accept ticket in status {ticket.status}")
        
        # Check role - issuer or manager
        if self.ctx.user_id != ticket.created_by and self.ctx.role not in [Role.MANAGER, Role.SYS_ADMIN]:
            raise ForbiddenError("Only issuer or MANAGER can accept ticket")
        
        # Update status
        ticket.status = "CLOSED"
        ticket.closed_at = utcnow()
        
        # Record event
        await self._record_event(ticket.id, "ACCEPTED", {"accepted_by": str(self.ctx.user_id)})
        await self._record_event(ticket.id, "CLOSED", {"closed_by": str(self.ctx.user_id)})
        
        await self.db.commit()
        
        # Emit events
        await publish("ticket.accepted", {
            "ticket_id": str(ticket.id),
        })
        await publish("ticket.closed", {
            "ticket_id": str(ticket.id),
        })
        
        # Notify maintenance
        notify = get_service("notify", "NotifyService")
        if notify and ticket.assigned_to:
            await notify.notify_user(
                user_id=ticket.assigned_to,
                event="ticket.accepted",
                data={"ticket_id": str(ticket.id), "code": ticket.code},
            )
        
        logger.info(f"Ticket accepted and closed: {ticket.id}")
        return ticket
    
    async def escalate(self, ticket_id: UUID, data: Optional[EscalateRequest] = None) -> Ticket:
        """
        Escalate ticket (issuer, MANAGER, or auto).
        -> ESCALATED_TO_MANAGER
        """
        ticket = await self._get_ticket(ticket_id)
        
        # Check role
        if self.ctx.role not in [Role.OPERATOR, Role.MANAGER, Role.SYS_ADMIN, Role.MAINTENANCE]:
            # Issuer can escalate
            if self.ctx.user_id != ticket.created_by:
                raise ForbiddenError("Only issuer, MAINTENANCE, or MANAGER can escalate")
        
        # Update status
        ticket.status = "ESCALATED_TO_MANAGER"
        ticket.escalated_at = utcnow()
        ticket.escalated_by = self.ctx.user_id
        
        # Record event
        await self._record_event(ticket.id, "ESCALATED", {"reason": data.reason if data else None})
        
        await self.db.commit()
        
        # Emit event
        await publish("ticket.escalated", {
            "ticket_id": str(ticket.id),
            "escalated_by": str(self.ctx.user_id),
            "reason": data.reason if data else None,
        })
        
        # Notify managers
        notify = get_service("notify", "NotifyService")
        if notify:
            await notify.notify_role(
                org_id=self.ctx.org_id,
                role=Role.MANAGER,
                event="ticket.escalated",
                data={"ticket_id": str(ticket.id), "code": ticket.code},
            )
        
        logger.info(f"Ticket escalated: {ticket.id}")
        return ticket
    
    async def manager_decision(self, ticket_id: UUID, data: ManagerDecision) -> Ticket:
        """
        Manager decision on escalated ticket.
        FORCE_CLOSE, REQUIRE_NEW_TICKET, or MANDATE_ACTION.
        """
        ticket = await self._get_ticket(ticket_id)
        
        # Check role
        if self.ctx.role not in [Role.MANAGER, Role.SYS_ADMIN]:
            raise ForbiddenError("Only MANAGER can make decisions on escalated tickets")
        
        # Validate escalation status
        if ticket.status != "ESCALATED_TO_MANAGER":
            raise InvalidTransitionError(f"Ticket is not escalated (status: {ticket.status})")
        
        # Record event
        await self._record_event(ticket.id, "MANAGER_DECISION", {"decision": data.decision, "note": data.note})
        
        if data.decision == "FORCE_CLOSE":
            ticket.status = "CLOSED"
            ticket.closed_at = utcnow()
            await self._record_event(ticket.id, "CLOSED", {"closed_by": str(self.ctx.user_id), "manager_decision": True})
        elif data.decision == "REQUIRE_NEW_TICKET":
            # Keep current ticket open, require new one
            ticket.status = "IN_PROGRESS"
            # Could add a note/flag indicating new ticket required
        elif data.decision == "MANDATE_ACTION":
            # Return to maintenance with mandate
            ticket.status = "IN_PROGRESS"
            # Add mandate note to ticket
        
        await self.db.commit()
        
        # Emit event
        await publish("ticket.manager_decision", {
            "ticket_id": str(ticket.id),
            "decision": data.decision,
            "note": data.note,
        })
        
        logger.info(f"Manager decision on ticket {ticket.id}: {data.decision}")
        return ticket
    
    async def for_node(self, node_id: UUID) -> Dict[str, Any]:
        """Get active + historical tickets for a node."""
        stmt = select(Ticket).where(
            Ticket.service_point_id == node_id,
            Ticket.organization_id == self.ctx.org_id,
            Ticket.deleted_at.is_(None),
        )
        result = await self.db.execute(stmt)
        tickets = result.scalars().all()
        
        return {
            "node_id": str(node_id),
            "active_count": sum(1 for t in tickets if t.status not in ["CLOSED"]),
            "historical_count": sum(1 for t in tickets if t.status == "CLOSED"),
            "tickets": [
                {
                    "id": str(t.id),
                    "code": t.code,
                    "status": t.status,
                    "priority": t.priority,
                    "created_at": t.created_at.isoformat(),
                }
                for t in tickets
            ],
        }


class FileService:
    """Service for file operations."""
    
    ALLOWED_MIMES = {
        "image/jpeg",
        "image/png",
        "application/pdf",
        "text/plain",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # DOCX
    }
    ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf", ".txt", ".docx"}
    MAX_SIZE = 10 * 1024 * 1024  # 10 MB default
    BLOCKED_EXECUTABLES = {".exe", ".bat", ".sh", ".cmd", ".ps1", ".msi"}
    
    def __init__(self, db_session: AsyncSession, ctx: RequestContext):
        self.db = db_session
        self.ctx = ctx
    
    def _validate_upload(self, filename: str, mime_claimed: str, size: int, head: Optional[bytes] = None) -> List[str]:
        """
        Validate file upload.
        Returns list of violation codes.
        """
        violations = []
        
        # Check size
        if size > self.MAX_SIZE:
            violations.append("SIZE_EXCEEDED")
        
        # Check extension
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext in self.BLOCKED_EXECUTABLES:
            violations.append("EXECUTABLE_BLOCKED")
        elif ext not in self.ALLOWED_EXTENSIONS:
            violations.append("EXT_BLOCKED")
        
        # Check MIME
        if mime_claimed not in self.ALLOWED_MIMES:
            violations.append("MIME_INVALID")
        
        # Sniff MIME if head provided (would use python-magic in production)
        if head and len(head) > 0:
            # Simplified sniffing - in production use python-magic
            sniffed_mime = self._sniff_mime(head)
            if sniffed_mime and sniffed_mime != mime_claimed:
                violations.append("MIME_MISMATCH")
        
        return violations
    
    def _sniff_mime(self, head: bytes) -> Optional[str]:
        """Sniff MIME type from file head."""
        # Simplified implementation - use python-magic in production
        if head.startswith(b"%PDF"):
            return "application/pdf"
        elif head.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        elif head.startswith(b"\x89PNG"):
            return "image/png"
        return None
    
    async def validate_and_upload(self, stream: Any, meta: FileUploadMeta) -> File:
        """
        Upload a file with validation.
        
        Validates: MIME, extension, size, executables
        Stores via STORAGE module
        Persists metadata
        """
        # Read file content for validation
        content = await stream.read()
        
        # Validate
        violations = self._validate_upload(meta.original_name, meta.mime, len(content), content[:512])
        if violations:
            raise DomainError(
                error_code="FILE_VALIDATION_FAILED",
                message=f"File validation failed: {', '.join(violations)}",
                details={"violations": violations},
            )
        
        # Get STORAGE service
        storage = get_service("storage", "StorageService")
        if not storage:
            raise DomainError(error_code="STORAGE_UNAVAILABLE", message="Storage service not available")
        
        # Build tenant key
        key = f"org-{self.ctx.org_id}/files/{new_id()}/{meta.original_name}"
        
        # Upload to storage
        await storage.put(key, content, meta.mime, max_bytes=self.MAX_SIZE)
        
        # Calculate content hash for duplicate detection
        content_hash = hashlib.sha256(content).hexdigest()
        
        # Create file record
        file = File(
            organization_id=self.ctx.org_id,
            original_name=meta.original_name,
            key=key,
            mime=meta.mime,
            size=len(content),
            content_hash=content_hash,
            uploaded_by=self.ctx.user_id,
            entity_type=meta.entity_type,
            entity_id=meta.entity_id,
            purpose=meta.purpose.value,
        )
        self.db.add(file)
        await self.db.commit()
        await self.db.refresh(file)
        
        # Emit event
        await publish("file.uploaded", {
            "file_id": str(file.id),
            "organization_id": str(self.ctx.org_id),
            "original_name": meta.original_name,
            "purpose": meta.purpose.value,
        })
        
        logger.info(f"File uploaded: {file.id}")
        return file
    
    async def get_file(self, file_id: UUID) -> File:
        """Get file metadata with permission check."""
        stmt = select(File).where(
            File.id == file_id,
            File.organization_id == self.ctx.org_id,
            File.deleted_at.is_(None),
        )
        result = await self.db.execute(stmt)
        file = result.scalar_one_or_none()
        
        if not file:
            raise NotFoundError(f"File {file_id} not found")
        
        # Check entity permission
        if file.entity_type and file.entity_id:
            # Would delegate to owning module (ASSETS, WORKORDERS, TICKETS)
            # For now, allow if org matches
            pass
        
        return file
    
    async def download_url(self, file_id: UUID, ttl_s: int = 900) -> str:
        """Get presigned download URL."""
        file = await self.get_file(file_id)
        
        storage = get_service("storage", "StorageService")
        if not storage:
            raise DomainError(error_code="STORAGE_UNAVAILABLE", message="Storage service not available")
        
        # Cap TTL at 1 hour
        ttl_s = min(ttl_s, 3600)
        
        url = await storage.presigned_url(file.key, ttl_s=ttl_s, method="GET")
        return url
    
    async def delete_file(self, file_id: UUID) -> None:
        """
        Soft-delete a file.
        Blocks where retention/audit requires.
        """
        file = await self.get_file(file_id)
        
        # Check retention rules (simplified - would check audit requirements)
        # For MVP, allow deletion
        
        # Mark as deleted
        file.deleted_at = utcnow()
        
        # Delete from storage
        storage = get_service("storage", "StorageService")
        if storage:
            await storage.delete(file.key)
        
        await self.db.commit()
        
        # Emit event
        await publish("file.deleted", {
            "file_id": str(file_id),
        })
        
        logger.info(f"File deleted: {file_id}")
    
    async def list_for_entity(self, entity_type: str, entity_id: UUID, purpose: Optional[FilePurpose] = None) -> List[Dict[str, Any]]:
        """List files linked to an entity."""
        stmt = select(File).where(
            File.entity_type == entity_type,
            File.entity_id == entity_id,
            File.organization_id == self.ctx.org_id,
            File.deleted_at.is_(None),
        )
        
        if purpose:
            stmt = stmt.where(File.purpose == purpose.value)
        
        result = await self.db.execute(stmt)
        files = result.scalars().all()
        
        return [
            {
                "id": str(f.id),
                "original_name": f.original_name,
                "mime": f.mime,
                "size": f.size,
                "purpose": f.purpose,
                "uploaded_at": f.uploaded_at.isoformat(),
                "ingestion_status": f.ingestion_status,
            }
            for f in files
        ]
    
    async def attach(self, entity_type: str, entity_id: UUID, file_id: UUID) -> File:
        """
        Link existing file to an entity.
        THE port used by WORKORDERS/TICKETS/ASSETS.
        """
        file = await self.get_file(file_id)
        
        # Update linkage
        file.entity_type = entity_type
        file.entity_id = entity_id
        
        await self.db.commit()
        
        logger.info(f"File {file_id} attached to {entity_type}:{entity_id}")
        return file
    
    async def mark_for_ingestion(self, file_id: UUID) -> File:
        """
        Mark file for AI ingestion.
        Only PDF/TXT/DOCX allowed.
        """
        file = await self.get_file(file_id)
        
        # Check file type
        allowed_for_ingestion = {"application/pdf", "text/plain", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
        if file.mime not in allowed_for_ingestion:
            raise DomainError(
                error_code="INGESTION_NOT_ALLOWED",
                message=f"File type {file.mime} not allowed for ingestion",
            )
        
        # Update status
        file.ingestion_status = "PENDING"
        
        await self.db.commit()
        
        # Emit event for AI module to consume
        await publish("manual.ingestion_requested", {
            "file_id": str(file_id),
            "organization_id": str(self.ctx.org_id),
            "node_id": str(file.entity_id) if file.entity_type == "SERVICE_POINT" else None,
        })
        
        logger.info(f"File marked for ingestion: {file_id}")
        return file
    
    async def set_ingestion_status(self, file_id: UUID, status: IngestionStatus, job_id: Optional[str] = None) -> None:
        """Set ingestion status (port for AI callbacks)."""
        stmt = select(File).where(File.id == file_id)
        result = await self.db.execute(stmt)
        file = result.scalar_one_or_none()
        
        if not file:
            raise NotFoundError(f"File {file_id} not found")
        
        file.ingestion_status = status.value
        if job_id:
            file.ingestion_job_id = job_id
        
        await self.db.commit()
    
    async def duplicate_policy(self, content_hash: str, entity_type: str, entity_id: UUID) -> DupDecision:
        """
        Check duplicate policy.
        Org-configured duplicate handling.
        """
        # Check for existing file with same hash
        stmt = select(File).where(
            File.content_hash == content_hash,
            File.entity_type == entity_type,
            File.entity_id == entity_id,
            File.deleted_at.is_(None),
        )
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()
        
        if not existing:
            return DupDecision(action=DupDecisionAction.ALLOW)
        
        # In production, would check org config for policy
        # For MVP, suggest versioning
        return DupDecision(
            action=DupDecisionAction.VERSION,
            reason=f"Duplicate of file {existing.id}",
        )


# ============================================================================
# FastAPI Router
# ============================================================================

router = APIRouter(prefix="/tickets", tags=["tickets"])


async def get_ctx(request: Any) -> RequestContext:
    """Extract request context."""
    # Would extract from request.state in real implementation
    return RequestContext(
        org_id=UUID("00000000-0000-0000-0000-000000000001"),
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        role=Role.MANAGER,
        request_id=new_id(),
        timezone="UTC",
    )


async def get_db() -> AsyncSession:
    """Get DB session."""
    db_module = get_service("db", "DatabaseService")
    if db_module:
        async with db_module.session_factory() as session:
            yield session


@router.post("", response_model=TicketView, status_code=status.HTTP_201_CREATED)
async def create_ticket_endpoint(
    data: TicketCreate,
    ctx: RequestContext = Depends(get_ctx),
    db: AsyncSession = Depends(get_db),
):
    """Create a repair ticket."""
    service = TicketService(db, ctx)
    ticket = await service.create_ticket(data)
    return TicketView(
        id=ticket.id,
        code=ticket.code,
        service_point_id=ticket.service_point_id,
        service_point_name=None,
        status=TicketStatus(ticket.status),
        priority=TicketPriority(ticket.priority),
        description=ticket.description,
        created_at=ticket.created_at,
        created_by=ticket.created_by,
        assigned_to=ticket.assigned_to,
        loop_counter=ticket.loop_counter,
        has_escalation=False,
    )


@router.get("", response_model=PageType)
async def list_tickets_endpoint(
    filters: Optional[Dict] = None,
    page: int = 1,
    page_size: int = 50,
    ctx: RequestContext = Depends(get_ctx),
    db: AsyncSession = Depends(get_db),
):
    """List tickets."""
    service = TicketService(db, ctx)
    return await service.list_tickets(filters, page, page_size)


@router.get("/{ticket_id}", response_model=TicketDetail)
async def get_ticket_endpoint(
    ticket_id: UUID,
    ctx: RequestContext = Depends(get_ctx),
    db: AsyncSession = Depends(get_db),
):
    """Get ticket detail."""
    service = TicketService(db, ctx)
    return await service.get_ticket(ticket_id)


@router.post("/{ticket_id}/claim", response_model=TicketView)
async def claim_ticket_endpoint(
    ticket_id: UUID,
    data: ClaimRequest = ClaimRequest(),
    ctx: RequestContext = Depends(get_ctx),
    db: AsyncSession = Depends(get_db),
):
    """Claim a ticket."""
    service = TicketService(db, ctx)
    ticket = await service.claim(ticket_id)
    return TicketView(
        id=ticket.id,
        code=ticket.code,
        service_point_id=ticket.service_point_id,
        service_point_name=None,
        status=TicketStatus(ticket.status),
        priority=TicketPriority(ticket.priority),
        description=ticket.description,
        created_at=ticket.created_at,
        created_by=ticket.created_by,
        assigned_to=ticket.assigned_to,
        loop_counter=ticket.loop_counter,
        has_escalation=ticket.escalated_at is not None,
    )


@router.post("/{ticket_id}/assign", response_model=TicketView)
async def assign_ticket_endpoint(
    ticket_id: UUID,
    data: AssignRequest,
    ctx: RequestContext = Depends(get_ctx),
    db: AsyncSession = Depends(get_db),
):
    """Assign a ticket."""
    service = TicketService(db, ctx)
    ticket = await service.assign(ticket_id, data.user_id)
    return TicketView(
        id=ticket.id,
        code=ticket.code,
        service_point_id=ticket.service_point_id,
        service_point_name=None,
        status=TicketStatus(ticket.status),
        priority=TicketPriority(ticket.priority),
        description=ticket.description,
        created_at=ticket.created_at,
        created_by=ticket.created_by,
        assigned_to=ticket.assigned_to,
        loop_counter=ticket.loop_counter,
        has_escalation=ticket.escalated_at is not None,
    )


@router.post("/{ticket_id}/report", response_model=TicketView)
async def submit_report_endpoint(
    ticket_id: UUID,
    data: ReportSubmit,
    ctx: RequestContext = Depends(get_ctx),
    db: AsyncSession = Depends(get_db),
):
    """Submit maintenance report."""
    service = TicketService(db, ctx)
    ticket = await service.submit_report(ticket_id, data)
    return TicketView(
        id=ticket.id,
        code=ticket.code,
        service_point_id=ticket.service_point_id,
        service_point_name=None,
        status=TicketStatus(ticket.status),
        priority=TicketPriority(ticket.priority),
        description=ticket.description,
        created_at=ticket.created_at,
        created_by=ticket.created_by,
        assigned_to=ticket.assigned_to,
        loop_counter=ticket.loop_counter,
        has_escalation=ticket.escalated_at is not None,
    )


@router.post("/{ticket_id}/feedback", response_model=TicketView)
async def submit_feedback_endpoint(
    ticket_id: UUID,
    data: FeedbackSubmit,
    ctx: RequestContext = Depends(get_ctx),
    db: AsyncSession = Depends(get_db),
):
    """Submit issuer feedback."""
    service = TicketService(db, ctx)
    ticket = await service.submit_feedback(ticket_id, data)
    return TicketView(
        id=ticket.id,
        code=ticket.code,
        service_point_id=ticket.service_point_id,
        service_point_name=None,
        status=TicketStatus(ticket.status),
        priority=TicketPriority(ticket.priority),
        description=ticket.description,
        created_at=ticket.created_at,
        created_by=ticket.created_by,
        assigned_to=ticket.assigned_to,
        loop_counter=ticket.loop_counter,
        has_escalation=ticket.escalated_at is not None,
    )


@router.post("/{ticket_id}/accept", response_model=TicketView)
async def accept_ticket_endpoint(
    ticket_id: UUID,
    ctx: RequestContext = Depends(get_ctx),
    db: AsyncSession = Depends(get_db),
):
    """Accept and close a ticket."""
    service = TicketService(db, ctx)
    ticket = await service.accept_ticket(ticket_id)
    return TicketView(
        id=ticket.id,
        code=ticket.code,
        service_point_id=ticket.service_point_id,
        service_point_name=None,
        status=TicketStatus(ticket.status),
        priority=TicketPriority(ticket.priority),
        description=ticket.description,
        created_at=ticket.created_at,
        created_by=ticket.created_by,
        assigned_to=ticket.assigned_to,
        loop_counter=ticket.loop_counter,
        has_escalation=ticket.escalated_at is not None,
    )


@router.post("/{ticket_id}/escalate", response_model=TicketView)
async def escalate_ticket_endpoint(
    ticket_id: UUID,
    data: Optional[EscalateRequest] = None,
    ctx: RequestContext = Depends(get_ctx),
    db: AsyncSession = Depends(get_db),
):
    """Escalate a ticket."""
    service = TicketService(db, ctx)
    ticket = await service.escalate(ticket_id, data)
    return TicketView(
        id=ticket.id,
        code=ticket.code,
        service_point_id=ticket.service_point_id,
        service_point_name=None,
        status=TicketStatus(ticket.status),
        priority=TicketPriority(ticket.priority),
        description=ticket.description,
        created_at=ticket.created_at,
        created_by=ticket.created_by,
        assigned_to=ticket.assigned_to,
        loop_counter=ticket.loop_counter,
        has_escalation=ticket.escalated_at is not None,
    )


@router.post("/{ticket_id}/decision", response_model=TicketView)
async def manager_decision_endpoint(
    ticket_id: UUID,
    data: ManagerDecision,
    ctx: RequestContext = Depends(get_ctx),
    db: AsyncSession = Depends(get_db),
):
    """Manager decision on escalated ticket."""
    service = TicketService(db, ctx)
    ticket = await service.manager_decision(ticket_id, data)
    return TicketView(
        id=ticket.id,
        code=ticket.code,
        service_point_id=ticket.service_point_id,
        service_point_name=None,
        status=TicketStatus(ticket.status),
        priority=TicketPriority(ticket.priority),
        description=ticket.description,
        created_at=ticket.created_at,
        created_by=ticket.created_by,
        assigned_to=ticket.assigned_to,
        loop_counter=ticket.loop_counter,
        has_escalation=ticket.escalated_at is not None,
    )


# Files router
files_router = APIRouter(prefix="/files", tags=["files"])


@files_router.post("/upload", response_model=FileView, status_code=status.HTTP_201_CREATED)
async def upload_file_endpoint(
    file: UploadFile = FastAPIFile(...),
    purpose: FilePurpose = FilePurpose.ATTACHMENT,
    ctx: RequestContext = Depends(get_ctx),
    db: AsyncSession = Depends(get_db),
):
    """Upload a file."""
    service = FileService(db, ctx)
    meta = FileUploadMeta(
        original_name=file.filename or "unnamed",
        mime=file.content_type or "application/octet-stream",
        size=0,  # Will be calculated
        purpose=purpose,
    )
    uploaded = await service.validate_and_upload(file, meta)
    return FileView(
        id=uploaded.id,
        original_name=uploaded.original_name,
        key=uploaded.key,
        mime=uploaded.mime,
        size=uploaded.size,
        uploaded_by=uploaded.uploaded_by,
        entity_type=uploaded.entity_type,
        entity_id=uploaded.entity_id,
        purpose=FilePurpose(uploaded.purpose),
        ingestion_status=IngestionStatus(uploaded.ingestion_status) if uploaded.ingestion_status else None,
        uploaded_at=uploaded.uploaded_at,
    )


@files_router.get("/{file_id}", response_model=FileView)
async def get_file_endpoint(
    file_id: UUID,
    ctx: RequestContext = Depends(get_ctx),
    db: AsyncSession = Depends(get_db),
):
    """Get file metadata."""
    service = FileService(db, ctx)
    file = await service.get_file(file_id)
    return FileView(
        id=file.id,
        original_name=file.original_name,
        key=file.key,
        mime=file.mime,
        size=file.size,
        uploaded_by=file.uploaded_by,
        entity_type=file.entity_type,
        entity_id=file.entity_id,
        purpose=FilePurpose(file.purpose),
        ingestion_status=IngestionStatus(file.ingestion_status) if file.ingestion_status else None,
        uploaded_at=file.uploaded_at,
    )


@files_router.get("/{file_id}/download-url")
async def download_url_endpoint(
    file_id: UUID,
    ctx: RequestContext = Depends(get_ctx),
    db: AsyncSession = Depends(get_db),
):
    """Get presigned download URL."""
    service = FileService(db, ctx)
    url = await service.download_url(file_id)
    return {"url": url}


@files_router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file_endpoint(
    file_id: UUID,
    ctx: RequestContext = Depends(get_ctx),
    db: AsyncSession = Depends(get_db),
):
    """Delete a file."""
    service = FileService(db, ctx)
    await service.delete_file(file_id)


@files_router.get("/entity/{entity_type}/{entity_id}", response_model=List[Dict])
async def list_files_for_entity_endpoint(
    entity_type: str,
    entity_id: UUID,
    purpose: Optional[FilePurpose] = None,
    ctx: RequestContext = Depends(get_ctx),
    db: AsyncSession = Depends(get_db),
):
    """List files for an entity."""
    service = FileService(db, ctx)
    return await service.list_for_entity(entity_type, entity_id, purpose)


@files_router.post("/{file_id}/attach")
async def attach_file_endpoint(
    file_id: UUID,
    entity_type: str,
    entity_id: UUID,
    ctx: RequestContext = Depends(get_ctx),
    db: AsyncSession = Depends(get_db),
):
    """Attach file to entity."""
    service = FileService(db, ctx)
    file = await service.attach(entity_type, entity_id, file_id)
    return FileView(
        id=file.id,
        original_name=file.original_name,
        key=file.key,
        mime=file.mime,
        size=file.size,
        uploaded_by=file.uploaded_by,
        entity_type=file.entity_type,
        entity_id=file.entity_id,
        purpose=FilePurpose(file.purpose),
        ingestion_status=IngestionStatus(file.ingestion_status) if file.ingestion_status else None,
        uploaded_at=file.uploaded_at,
    )


@files_router.post("/{file_id}/ingest", response_model=FileView)
async def mark_for_ingestion_endpoint(
    file_id: UUID,
    ctx: RequestContext = Depends(get_ctx),
    db: AsyncSession = Depends(get_db),
):
    """Mark file for AI ingestion."""
    service = FileService(db, ctx)
    file = await service.mark_for_ingestion(file_id)
    return FileView(
        id=file.id,
        original_name=file.original_name,
        key=file.key,
        mime=file.mime,
        size=file.size,
        uploaded_by=file.uploaded_by,
        entity_type=file.entity_type,
        entity_id=file.entity_id,
        purpose=FilePurpose(file.purpose),
        ingestion_status=IngestionStatus(file.ingestion_status) if file.ingestion_status else None,
        uploaded_at=file.uploaded_at,
    )


# ============================================================================
# Module Classes
# ============================================================================

class TicketsModule(ModuleBase):
    """TICKETS Module."""
    
    name = "tickets"
    version = "1.0.0"
    dependencies = {"core", "db", "api", "assets", "tenancy"}
    optional_dependencies = {"notify", "files"}
    profiles = {"api", "worker", "all-in-one"}
    
    def __init__(self):
        self._ctx = None
        self._healthy = False
    
    async def configure(self, settings: Dict[str, Any]) -> None:
        logger.info("Configuring TICKETS module")
        self._healthy = True
    
    async def initialize(self, ctx: ModuleContext) -> None:
        self._ctx = ctx
        logger.info("Initialized TICKETS module")
    
    async def start(self) -> None:
        # Register routes
        api = get_service("api", "ApiService")
        if api:
            api.register_router(router, prefix="/tickets", tags=["tickets"])
            api.register_router(files_router, prefix="/files", tags=["files"])
        
        logger.info("TICKETS module started")
    
    async def stop(self) -> None:
        logger.info("Stopping TICKETS module")
        self._healthy = False
    
    async def health(self) -> HealthReport:
        return HealthReport(
            module=self.name,
            status=HealthStatus.HEALTHY if self._healthy else HealthStatus.UNAVAILABLE,
            checks={"module_ready": self._healthy},
        )


class FilesModule(ModuleBase):
    """FILES Module."""
    
    name = "files"
    version = "1.0.0"
    dependencies = {"core", "db", "api", "storage", "tenancy"}
    optional_dependencies = {}
    profiles = {"api", "worker", "all-in-one"}
    
    def __init__(self):
        self._ctx = None
        self._healthy = False
    
    async def configure(self, settings: Dict[str, Any]) -> None:
        logger.info("Configuring FILES module")
        self._healthy = True
    
    async def initialize(self, ctx: ModuleContext) -> None:
        self._ctx = ctx
        logger.info("Initialized FILES module")
    
    async def start(self) -> None:
        # Routes already registered by TicketsModule
        logger.info("FILES module started")
    
    async def stop(self) -> None:
        logger.info("Stopping FILES module")
        self._healthy = False
    
    async def health(self) -> HealthReport:
        return HealthReport(
            module=self.name,
            status=HealthStatus.HEALTHY if self._healthy else HealthStatus.UNAVAILABLE,
            checks={"module_ready": self._healthy},
        )
