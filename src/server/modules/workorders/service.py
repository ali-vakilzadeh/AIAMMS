"""
WORKORDERS Module - Execution Engine for Maintenance Work Orders

This module handles the full lifecycle of work orders:
- Generation from cycle.due events (emitted by CYCLES module)
- Acknowledge/reject/snooze workflows
- Item execution with measurements, signatures, comments
- State machine transitions and completion tracking
- Integration with ASSETS (safety flags), FILES (attachments), NOTIFY (notifications)
"""

import asyncio
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Literal, Set
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import select, func, text as sql_text, Index, UniqueConstraint
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException, status

from ...shared.types import (
    RequestContext,
    Role,
    DomainError,
    NotFoundError,
    ForbiddenError,
    QuotaExceededError,
    InvalidTransitionError,
    Page,
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

class WorkOrderStatus(str, Enum):
    """Work order state machine states."""
    GENERATED = "GENERATED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    SNOOZED = "SNOOZED"
    REJECTED = "REJECTED"
    OVERDUE = "OVERDUE"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"


class ItemStatus(str, Enum):
    """Work item status values."""
    PENDING = "PENDING"
    TASK = "TASK"
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PENDING_PREDECESSOR = "PENDING_PREDECESSOR"
    PERFORMED_BY = "PERFORMED_BY"


class TriggerSource(str, Enum):
    """Source of work order generation."""
    AUTO = "AUTO"
    MANUAL = "MANUAL"
    MISSED = "MISSED"


class MeasurementType(str, Enum):
    """Measurement data types."""
    NUMERIC = "NUMERIC"
    TEXT = "TEXT"
    BOOLEAN = "BOOLEAN"


# ============================================================================
# Data Models (Pydantic)
# ============================================================================

class MeasurementFieldSpec(BaseModel):
    """Measurement field specification from template snapshot."""
    name: str
    data_type: MeasurementType = MeasurementType.NUMERIC
    unit: Optional[str] = None
    lower_threshold: Optional[float] = None
    upper_threshold: Optional[float] = None
    required: bool = False


class WorkItemSnapshot(BaseModel):
    """Frozen snapshot of a work item from template."""
    id: str
    activity_number: int
    predecessor: Optional[str]
    description: str
    status: str = "PENDING"
    priority: int = 50
    measurement_fields: Optional[List[MeasurementFieldSpec]] = None
    signature_required: bool = False
    safety_permit: Optional[str] = None
    risk: Optional[str] = None
    assignee: Optional[str] = None
    skills: Optional[List[str]] = None
    certs: Optional[List[str]] = None
    tools: Optional[List[str]] = None
    parts: Optional[List[str]] = None
    cost: Optional[float] = None
    downtime: Optional[int] = None
    notes: Optional[str] = None
    started_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    performed_by: Optional[str] = None


class WorkOrderCreate(BaseModel):
    """Internal model for work order creation from cycle."""
    cycle_id: UUID
    trigger_ctx: Dict[str, Any]  # {trigger_id, period_key, overdue, source}


class WorkOrderView(BaseModel):
    """Full work order view for API responses."""
    id: UUID
    code: str
    cycle_id: UUID
    target_entity_type: str
    target_entity_id: UUID
    status: WorkOrderStatus
    title: str
    description: Optional[str]
    deadline: datetime
    grace_period_end: Optional[datetime]
    created_at: datetime
    acknowledged_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    closed_at: Optional[datetime]
    completion_percentage: int
    assigned_to: Optional[UUID]
    items_count: int
    has_overdue_flag: bool


class WorkOrderDetail(BaseModel):
    """Detailed work order with items and metadata."""
    id: UUID
    code: str
    cycle_id: UUID
    target_entity_type: str
    target_entity_id: UUID
    status: WorkOrderStatus
    title: str
    description: Optional[str]
    deadline: datetime
    grace_period_end: Optional[datetime]
    deadline_behavior: str
    safety_flag: Optional[str]
    created_at: datetime
    created_by: UUID
    acknowledged_at: Optional[datetime]
    viewed_by: Optional[UUID]
    first_view_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    closed_at: Optional[datetime]
    closed_by: Optional[UUID]
    quality_check_by: Optional[UUID]
    completion_percentage: int
    assigned_to: Optional[UUID]
    items: List[Dict[str, Any]]
    comments: List[Dict[str, Any]]
    attachments: List[Dict[str, Any]]
    measurements: List[Dict[str, Any]]
    signatures: List[Dict[str, Any]]
    snooze_records: List[Dict[str, Any]]
    rejection_records: List[Dict[str, Any]]
    linked_ticket_id: Optional[UUID]
    effective_flags: List[Dict[str, Any]]


class AcknowledgeRequest(BaseModel):
    """Request to acknowledge a work order."""
    pass


class RejectRequest(BaseModel):
    """Request to reject a work order."""
    reason: str = Field(..., min_length=1, description="Rejection reason is required")


class SnoozeRequest(BaseModel):
    """Request to snooze a work order."""
    duration: Literal["1h", "6h", "12h", "1d", "3d", "6d"]
    reason: str = Field(..., min_length=1, description="Snooze reason is required")


class ResumeRequest(BaseModel):
    """Request to resume a snoozed work order."""
    pass


class ItemUpdate(BaseModel):
    """Request to update a work item."""
    status: Optional[ItemStatus] = None
    notes: Optional[str] = None
    started_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    performed_by: Optional[str] = None


class MeasurementRecord(BaseModel):
    """Request to record a measurement."""
    value: Any  # Can be number, string, or boolean


class CommentCreate(BaseModel):
    """Request to add a comment."""
    text: str
    parent_comment_id: Optional[str] = None


class SignatureCreate(BaseModel):
    """Request to add a signature."""
    signature: str  # Digital signature data


class CompleteRequest(BaseModel):
    """Request to complete a work order."""
    cost: Optional[float] = None
    downtime: Optional[int] = None


class CloseRequest(BaseModel):
    """Request to close a work order."""
    quality_check_by: Optional[str] = None


# ============================================================================
# SQLAlchemy Models
# ============================================================================

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import ForeignKey

class Base(DeclarativeBase):
    pass


class WorkOrder(Base):
    __tablename__ = "work_orders"
    
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(index=True, nullable=False)
    code: Mapped[str] = mapped_column(unique=True, index=True, nullable=False)
    cycle_id: Mapped[UUID] = mapped_column(index=True, nullable=False)
    period_key: Mapped[str] = mapped_column(nullable=False)  # For idempotency
    target_entity_type: Mapped[str] = mapped_column(nullable=False)
    target_entity_id: Mapped[UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(default="GENERATED")
    title: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[Optional[str]]
    deadline: Mapped[datetime]
    grace_period_end: Mapped[Optional[datetime]]
    deadline_behavior: Mapped[str]
    safety_flag: Mapped[Optional[str]]
    launch_mode: Mapped[str]
    trigger_source: Mapped[str]  # AUTO|MANUAL|MISSED
    created_at: Mapped[datetime] = mapped_column(default=lambda: utcnow())
    created_by: Mapped[UUID]
    acknowledged_at: Mapped[Optional[datetime]]
    viewed_by: Mapped[Optional[UUID]]
    first_view_at: Mapped[Optional[datetime]]
    started_at: Mapped[Optional[datetime]]
    completed_at: Mapped[Optional[datetime]]
    closed_at: Mapped[Optional[datetime]]
    closed_by: Mapped[Optional[UUID]]
    quality_check_by: Mapped[Optional[str]]
    completion_percentage: Mapped[int] = mapped_column(default=0)
    assigned_to: Mapped[Optional[UUID]] = mapped_column(index=True)
    has_overdue_flag: Mapped[bool] = mapped_column(default=False)
    cost: Mapped[Optional[float]]
    downtime: Mapped[Optional[int]]  # minutes
    deleted_at: Mapped[Optional[datetime]]
    
    # Relationships
    items: Mapped[List["WorkOrderItem"]] = relationship(
        back_populates="work_order", 
        cascade="all, delete-orphan",
        foreign_keys="WorkOrderItem.work_order_id"
    )
    comments: Mapped[List["WorkOrderComment"]] = relationship(
        back_populates="work_order",
        cascade="all, delete-orphan"
    )
    attachments: Mapped[List["WorkOrderAttachment"]] = relationship(
        back_populates="work_order",
        cascade="all, delete-orphan"
    )
    signatures: Mapped[List["WorkOrderSignature"]] = relationship(
        back_populates="work_order",
        cascade="all, delete-orphan"
    )
    measurements: Mapped[List["WorkOrderItemMeasurement"]] = relationship(
        back_populates="work_order",
        cascade="all, delete-orphan"
    )
    snooze_records: Mapped[List["SnoozeRecord"]] = relationship(
        back_populates="work_order",
        cascade="all, delete-orphan"
    )
    rejection_records: Mapped[List["RejectionRecord"]] = relationship(
        back_populates="work_order",
        cascade="all, delete-orphan"
    )
    
    __table_args__ = (
        UniqueConstraint("cycle_id", "period_key", name="uq_cycle_period"),
        Index("ix_work_orders_org_status", "organization_id", "status"),
        Index("ix_work_orders_deadline", "deadline"),
        Index("ix_work_orders_assigned", "assigned_to"),
        Index("ix_work_orders_target", "target_entity_type", "target_entity_id"),
    )


class WorkOrderItem(Base):
    __tablename__ = "work_order_items"
    
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: new_id())
    work_order_id: Mapped[UUID] = mapped_column(ForeignKey("work_orders.id"), index=True, nullable=False)
    item_snapshot_id: Mapped[str]  # From template snapshot
    activity_number: Mapped[int]
    predecessor: Mapped[Optional[str]]
    description: Mapped[str]
    status: Mapped[str] = mapped_column(default="PENDING")
    priority: Mapped[int] = mapped_column(default=50)
    measurement_fields: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    signature_required: Mapped[bool] = mapped_column(default=False)
    safety_permit: Mapped[Optional[str]]
    risk: Mapped[Optional[str]]
    assignee: Mapped[Optional[str]]
    skills: Mapped[Optional[List[str]]] = mapped_column(JSONB)
    certs: Mapped[Optional[List[str]]] = mapped_column(JSONB)
    tools: Mapped[Optional[List[str]]] = mapped_column(JSONB)
    parts: Mapped[Optional[List[str]]] = mapped_column(JSONB)
    cost: Mapped[Optional[float]]
    downtime: Mapped[Optional[int]]
    notes: Mapped[Optional[str]]
    started_at: Mapped[Optional[datetime]]
    closed_at: Mapped[Optional[datetime]]
    performed_by: Mapped[Optional[str]]
    created_at: Mapped[datetime] = mapped_column(default=lambda: utcnow())
    updated_at: Mapped[datetime] = mapped_column(default=lambda: utcnow(), onupdate=lambda: utcnow())
    
    work_order: Mapped["WorkOrder"] = relationship(back_populates="items")
    
    __table_args__ = (
        Index("ix_wo_items_wo", "work_order_id"),
        Index("ix_wo_items_status", "status"),
    )


class WorkOrderItemMeasurement(Base):
    __tablename__ = "work_order_item_measurements"
    
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: new_id())
    work_order_id: Mapped[UUID] = mapped_column(ForeignKey("work_orders.id"), index=True, nullable=False)
    item_id: Mapped[str]
    field_name: Mapped[str]
    value: Mapped[Any] = mapped_column(JSONB)
    recorded_at: Mapped[datetime] = mapped_column(default=lambda: utcnow())
    recorded_by: Mapped[UUID]
    passed: Mapped[Optional[bool]]  # Auto-calculated from thresholds
    
    work_order: Mapped["WorkOrder"] = relationship(back_populates="measurements")
    
    __table_args__ = (
        Index("ix_wo_meas_wo", "work_order_id"),
        Index("ix_wo_meas_item", "item_id"),
    )


class WorkOrderComment(Base):
    __tablename__ = "work_order_comments"
    
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: new_id())
    work_order_id: Mapped[UUID] = mapped_column(ForeignKey("work_orders.id"), index=True, nullable=False)
    parent_comment_id: Mapped[Optional[str]]
    text: Mapped[str]
    created_by: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(default=lambda: utcnow())
    deleted_at: Mapped[Optional[datetime]]
    
    work_order: Mapped["WorkOrder"] = relationship(back_populates="comments")


class WorkOrderAttachment(Base):
    __tablename__ = "work_order_attachments"
    
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: new_id())
    work_order_id: Mapped[UUID] = mapped_column(ForeignKey("work_orders.id"), index=True, nullable=False)
    item_id: Mapped[Optional[str]]  # If attached to specific item
    file_id: Mapped[UUID]
    attached_by: Mapped[UUID]
    attached_at: Mapped[datetime] = mapped_column(default=lambda: utcnow())
    
    work_order: Mapped["WorkOrder"] = relationship(back_populates="attachments")


class WorkOrderSignature(Base):
    __tablename__ = "work_order_signatures"
    
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: new_id())
    work_order_id: Mapped[UUID] = mapped_column(ForeignKey("work_orders.id"), index=True, nullable=False)
    item_id: Mapped[str]
    signer_id: Mapped[UUID]
    signature_data: Mapped[str]  # Digital signature
    signed_at: Mapped[datetime] = mapped_column(default=lambda: utcnow())
    
    work_order: Mapped["WorkOrder"] = relationship(back_populates="signatures")


class SnoozeRecord(Base):
    __tablename__ = "snooze_records"
    
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: new_id())
    work_order_id: Mapped[UUID] = mapped_column(ForeignKey("work_orders.id"), index=True, nullable=False)
    duration: Mapped[str]  # 1h, 6h, etc.
    reason: Mapped[str]
    snoozed_at: Mapped[datetime] = mapped_column(default=lambda: utcnow())
    snoozed_by: Mapped[UUID]
    resume_at: Mapped[datetime]
    resumed_at: Mapped[Optional[datetime]]
    previous_status: Mapped[str]
    
    work_order: Mapped["WorkOrder"] = relationship(back_populates="snooze_records")


class RejectionRecord(Base):
    __tablename__ = "rejection_records"
    
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: new_id())
    work_order_id: Mapped[UUID] = mapped_column(ForeignKey("work_orders.id"), index=True, nullable=False)
    reason: Mapped[str]
    rejected_at: Mapped[datetime] = mapped_column(default=lambda: utcnow())
    rejected_by: Mapped[UUID]
    
    work_order: Mapped["WorkOrder"] = relationship(back_populates="rejection_records")


# ============================================================================
# Module Class
# ============================================================================

class WorkOrdersModule(ModuleBase):
    """Work Orders module for maintenance execution management."""
    
    name = "workorders"
    version = "1.0.0"
    dependencies = ["core", "db", "api", "templates", "assets", "cache", "worker"]
    optional_dependencies = ["auth", "tenancy", "files", "notify"]
    profiles = ["api", "worker", "beat", "all-in-one"]
    
    def __init__(self):
        super().__init__()
        self.router = APIRouter(prefix="/work-orders", tags=["work-orders"])
        self._state_transitions = self._build_state_machine()
    
    async def configure(self, settings: Dict[str, Any]) -> None:
        """Configure work orders module."""
        self.settings = settings
        logger.info("WorkOrders module configured")
    
    async def initialize(self, ctx: ModuleContext) -> None:
        """Initialize work orders module."""
        self.db = await get_service("db", "DatabasePort")
        self.api = await get_service("api", "ApiPort")
        self.templates = await get_service("templates", "TemplatesPort", optional=True)
        self.assets = await get_service("assets", "AssetsPort", optional=True)
        self.cache = await get_service("cache", "CachePort", optional=True)
        self.worker = await get_service("worker", "TaskEnginePort", optional=True)
        self.auth = await get_service("auth", "AuthPort", optional=True)
        self.files = await get_service("files", "FilesPort", optional=True)
        self.notify = await get_service("notify", "NotifyPort", optional=True)
        
        # Register routes
        self._register_routes()
        
        # Subscribe to cycle events
        event_bus = get_event_bus()
        await event_bus.subscribe("cycle.due", self._on_cycle_due)
        await event_bus.subscribe("cycle.missed", self._on_cycle_missed)
        
        logger.info("WorkOrders module initialized")
    
    async def start(self) -> None:
        """Start work orders module."""
        # Register beat task for snooze resume
        if self.worker:
            await self.worker.register_beat(
                "workorders.resume_snoozed",
                "workorders.resume_snoozed_task",
                schedule=timedelta(minutes=1)
            )
            # Register beat task for overdue flagging
            await self.worker.register_beat(
                "workorders.flag_overdue",
                "workorders.flag_overdue_task",
                schedule=timedelta(minutes=5)
            )
        logger.info("WorkOrders module started")
    
    async def stop(self) -> None:
        """Stop work orders module."""
        logger.info("WorkOrders module stopped")
    
    async def health(self) -> HealthReport:
        """Health check for work orders module."""
        return HealthReport(
            module=self.name,
            status=HealthStatus.OK,
            details={"work_orders_active": True}
        )
    
    def _build_state_machine(self) -> Dict[str, Set[str]]:
        """Build valid state transitions."""
        return {
            "GENERATED": {"ACKNOWLEDGED", "REJECTED", "SNOOZED", "OVERDUE"},
            "ACKNOWLEDGED": {"IN_PROGRESS", "REJECTED", "SNOOZED", "OVERDUE"},
            "IN_PROGRESS": {"COMPLETED", "REJECTED", "SNOOZED", "BLOCKED", "OVERDUE"},
            "BLOCKED": {"IN_PROGRESS", "REJECTED", "OVERDUE"},
            "SNOOZED": {"ACKNOWLEDGED", "IN_PROGRESS", "OVERDUE"},  # Resume to previous state
            "REJECTED": set(),  # Terminal state
            "OVERDUE": {"IN_PROGRESS", "COMPLETED", "CLOSED"},
            "COMPLETED": {"CLOSED"},
            "CLOSED": set(),  # Terminal state
        }
    
    def _register_routes(self) -> None:
        """Register API routes."""
        self.api.register_router(self.router, "work-orders", ["work-orders"])
        
        # List work orders
        @self.router.get("")
        async def list_route(
            q: Optional[str] = None,
            status_filter: Optional[str] = None,
            page: int = 1,
            page_size: int = 50,
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await list_work_orders(ctx, q, status_filter, page, page_size)
        
        # Get work order detail
        @self.router.get("/{wo_id}")
        async def get_route(
            wo_id: UUID,
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await get_work_order(ctx, wo_id)
        
        # Acknowledge
        @self.router.post("/{wo_id}/acknowledge")
        async def acknowledge_route(
            wo_id: UUID,
            req: AcknowledgeRequest,
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await acknowledge(ctx, wo_id)
        
        # Reject
        @self.router.post("/{wo_id}/reject")
        async def reject_route(
            wo_id: UUID,
            req: RejectRequest,
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await reject(ctx, wo_id, req.reason)
        
        # Snooze
        @self.router.post("/{wo_id}/snooze")
        async def snooze_route(
            wo_id: UUID,
            req: SnoozeRequest,
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await snooze(ctx, wo_id, req.duration, req.reason)
        
        # Resume
        @self.router.post("/{wo_id}/resume")
        async def resume_route(
            wo_id: UUID,
            req: ResumeRequest,
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await resume(ctx, wo_id)
        
        # Update item
        @self.router.patch("/{wo_id}/items/{item_id}")
        async def update_item_route(
            wo_id: UUID,
            item_id: str,
            patch: ItemUpdate,
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await update_item(ctx, wo_id, item_id, patch)
        
        # Record measurement
        @self.router.post("/{wo_id}/items/{item_id}/measurement")
        async def measure_route(
            wo_id: UUID,
            item_id: str,
            measurement: MeasurementRecord,
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await record_measurement(ctx, wo_id, item_id, measurement.value)
        
        # Add comment
        @self.router.post("/{wo_id}/comments")
        async def comment_route(
            wo_id: UUID,
            comment: CommentCreate,
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await add_comment(ctx, wo_id, comment.text, comment.parent_comment_id)
        
        # Attach file
        @self.router.post("/{wo_id}/attachments")
        async def attach_route(
            wo_id: UUID,
            file_id: UUID,
            item_id: Optional[str] = None,
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await attach_file(ctx, wo_id, file_id, item_id)
        
        # Sign item
        @self.router.post("/{wo_id}/items/{item_id}/signature")
        async def sign_route(
            wo_id: UUID,
            item_id: str,
            sig: SignatureCreate,
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await sign(ctx, wo_id, item_id, sig.signature)
        
        # Complete
        @self.router.post("/{wo_id}/complete")
        async def complete_route(
            wo_id: UUID,
            req: CompleteRequest,
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await complete(ctx, wo_id, req.cost, req.downtime)
        
        # Close
        @self.router.post("/{wo_id}/close")
        async def close_route(
            wo_id: UUID,
            req: CloseRequest,
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await close_wo(ctx, wo_id, req.quality_check_by)


# ============================================================================
# Service Functions
# ============================================================================

async def generate_from_cycle(cycle_id: UUID, trigger_ctx: Dict[str, Any]) -> UUID:
    """
    Generate work order from cycle.due or cycle.missed event.
    Idempotent via unique(cycle_id, period_key).
    """
    session_factory = await get_service("db", "DatabasePort")
    templates = await get_service("templates", "TemplatesPort", optional=True)
    assets = await get_service("assets", "AssetsPort", optional=True)
    notify = await get_service("notify", "NotifyPort", optional=True)
    
    async with session_factory.session_factory()() as session:
        try:
            # Check idempotency
            existing = await session.execute(
                select(WorkOrder).where(
                    WorkOrder.cycle_id == cycle_id,
                    WorkOrder.period_key == trigger_ctx.get("period_key")
                )
            )
            existing_wo = existing.scalar_one_or_none()
            if existing_wo:
                logger.info(f"Work order already exists for cycle {cycle_id}, period {trigger_ctx.get('period_key')}")
                return existing_wo.id
            
            # Get cycle info (would normally fetch from DB)
            # For now, we'll use trigger_ctx
            target_entity_type = trigger_ctx.get("target_entity_type", "SERVICE_POINT")
            target_entity_id = trigger_ctx.get("target_entity_id")
            template_id = trigger_ctx.get("template_id")
            
            # Snapshot template
            if templates:
                snapshot = await templates.snapshot(template_id)
            else:
                # Placeholder - in production would fetch from templates module
                snapshot = TemplateSnapshot(
                    template_id=template_id,
                    kind="workflow",
                    code="TMPL-001",
                    name="Default Template",
                    items=[]
                )
            
            # Get target asset info
            if assets:
                asset_info = await assets.for_node(target_entity_id)
            else:
                asset_info = {"name": "Unknown Asset"}
            
            # Create work order
            wo_id = uuid4()
            wo_code = f"WO-{new_id()[:8].upper()}"
            deadline = utcnow() + timedelta(hours=trigger_ctx.get("deadline_hours", 72))
            grace_period_end = deadline + timedelta(hours=trigger_ctx.get("grace_hours", 24))
            
            wo = WorkOrder(
                id=wo_id,
                organization_id=trigger_ctx.get("org_id"),
                code=wo_code,
                cycle_id=cycle_id,
                period_key=trigger_ctx.get("period_key", utcnow().strftime("%Y-%m")),
                target_entity_type=target_entity_type,
                target_entity_id=target_entity_id,
                status="GENERATED",
                title=f"Maintenance: {asset_info.get('name', 'Unknown')}",
                description=snapshot.description if snapshot else None,
                deadline=deadline,
                grace_period_end=grace_period_end,
                deadline_behavior=trigger_ctx.get("deadline_behavior", "FLAG_CRITICAL_STOP"),
                safety_flag=trigger_ctx.get("safety_flag"),
                launch_mode=trigger_ctx.get("launch_mode", "AUTOMATIC"),
                trigger_source=trigger_ctx.get("source", "AUTO"),
                created_by=trigger_ctx.get("user_id", uuid4()),
                completion_percentage=0,
                has_overdue_flag=trigger_ctx.get("overdue", False),
            )
            
            session.add(wo)
            
            # Create items from snapshot
            if snapshot and snapshot.items:
                for item_snap in snapshot.items:
                    wo_item = WorkOrderItem(
                        work_order_id=wo_id,
                        item_snapshot_id=item_snap.id,
                        activity_number=item_snap.activity_number,
                        predecessor=item_snap.predecessor,
                        description=item_snap.description,
                        status=item_snap.status,
                        priority=item_snap.priority,
                        measurement_fields=[mf.dict() for mf in item_snap.measurement_fields] if item_snap.measurement_fields else None,
                        signature_required=item_snap.signature_required,
                        safety_permit=item_snap.safety_permit,
                        risk=item_snap.risk,
                        assignee=item_snap.assignee,
                        skills=item_snap.skills,
                        certs=item_snap.certs,
                        tools=item_snap.tools,
                        parts=item_snap.parts,
                        cost=item_snap.cost,
                        downtime=item_snap.downtime,
                        notes=item_snap.notes,
                    )
                    session.add(wo_item)
            
            await session.commit()
            
            # Emit event
            await publish("work_order.generated", {
                "work_order_id": str(wo_id),
                "cycle_id": str(cycle_id),
                "trigger_ctx": trigger_ctx,
            })
            
            # Notify assignee
            if notify:
                await notify.notify_role(
                    org_id=trigger_ctx.get("org_id"),
                    role="MAINTENANCE",
                    event="work_order.assigned",
                    data={"work_order_id": str(wo_id), "title": wo.title}
                )
            
            logger.info(f"Generated work order {wo_id} for cycle {cycle_id}")
            return wo_id
            
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to generate work order: {e}")
            raise


async def list_work_orders(
    ctx: RequestContext,
    q: Optional[str] = None,
    status_filter: Optional[str] = None,
    page: int = 1,
    page_size: int = 50
) -> Page:
    """List work orders with org-scoping and role filtering."""
    session_factory = await get_service("db", "DatabasePort")
    
    async with session_factory.org_scoped_session(ctx.org_id) as session:
        stmt = select(WorkOrder).where(
            WorkOrder.organization_id == ctx.org_id,
            WorkOrder.deleted_at.is_(None)
        )
        
        # Role-based filtering
        if ctx.role in ["OPERATOR", "MAINTENANCE"]:
            # Only see assigned or pool
            stmt = stmt.where(
                (WorkOrder.assigned_to == ctx.user_id) | 
                (WorkOrder.assigned_to.is_(None))
            )
        
        if q:
            stmt = stmt.where(WorkOrder.title.ilike(f"%{q}%"))
        
        if status_filter:
            stmt = stmt.where(WorkOrder.status == status_filter)
        
        # Pagination
        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await session.execute(total_stmt)).scalar()
        
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        results = await session.execute(stmt)
        items = results.scalars().all()
        
        return Page(
            items=[WorkOrderView(
                id=wo.id,
                code=wo.code,
                cycle_id=wo.cycle_id,
                target_entity_type=wo.target_entity_type,
                target_entity_id=wo.target_entity_id,
                status=wo.status,
                title=wo.title,
                description=wo.description,
                deadline=wo.deadline,
                grace_period_end=wo.grace_period_end,
                created_at=wo.created_at,
                acknowledged_at=wo.acknowledged_at,
                started_at=wo.started_at,
                completed_at=wo.completed_at,
                closed_at=wo.closed_at,
                completion_percentage=wo.completion_percentage,
                assigned_to=wo.assigned_to,
                items_count=len(wo.items),
                has_overdue_flag=wo.has_overdue_flag,
            ).dict() for wo in items],
            page=page,
            page_size=page_size,
            total=total
        )


async def get_work_order(ctx: RequestContext, wo_id: UUID) -> Dict[str, Any]:
    """Get full work order detail."""
    session_factory = await get_service("db", "DatabasePort")
    assets = await get_service("assets", "AssetsPort", optional=True)
    
    async with session_factory.org_scoped_session(ctx.org_id) as session:
        wo = await session.get(WorkOrder, wo_id)
        if not wo or wo.organization_id != ctx.org_id:
            raise NotFoundError("Work order not found")
        
        # Trigger acknowledge side-effect on first view
        if not wo.viewed_by and wo.status in ["GENERATED", "ACKNOWLEDGED"]:
            wo.viewed_by = ctx.user_id
            wo.first_view_at = utcnow()
            await session.commit()
        
        # Get effective flags from assets
        effective_flags = []
        if assets:
            effective_flags = await assets.effective_flags(wo.target_entity_id)
        
        return WorkOrderDetail(
            id=wo.id,
            code=wo.code,
            cycle_id=wo.cycle_id,
            target_entity_type=wo.target_entity_type,
            target_entity_id=wo.target_entity_id,
            status=wo.status,
            title=wo.title,
            description=wo.description,
            deadline=wo.deadline,
            grace_period_end=wo.grace_period_end,
            deadline_behavior=wo.deadline_behavior,
            safety_flag=wo.safety_flag,
            created_at=wo.created_at,
            created_by=wo.created_by,
            acknowledged_at=wo.acknowledged_at,
            viewed_by=wo.viewed_by,
            first_view_at=wo.first_view_at,
            started_at=wo.started_at,
            completed_at=wo.completed_at,
            closed_at=wo.closed_at,
            closed_by=wo.closed_by,
            quality_check_by=wo.quality_check_by,
            completion_percentage=wo.completion_percentage,
            assigned_to=wo.assigned_to,
            items=[item.dict() for item in wo.items],
            comments=[c.dict() for c in wo.comments],
            attachments=[a.dict() for a in wo.attachments],
            measurements=[m.dict() for m in wo.measurements],
            signatures=[s.dict() for s in wo.signatures],
            snooze_records=[s.dict() for s in wo.snooze_records],
            rejection_records=[r.dict() for r in wo.rejection_records],
            linked_ticket_id=None,  # Would join with tickets module
            effective_flags=effective_flags,
        ).dict()


async def acknowledge(ctx: RequestContext, wo_id: UUID) -> Dict[str, Any]:
    """Acknowledge a work order (idempotent)."""
    session_factory = await get_service("db", "DatabasePort")
    
    async with session_factory.org_scoped_session(ctx.org_id) as session:
        wo = await session.get(WorkOrder, wo_id)
        if not wo or wo.organization_id != ctx.org_id:
            raise NotFoundError("Work order not found")
        
        # Idempotent - allow re-acknowledge
        if wo.status == "ACKNOWLEDGED":
            return {"status": "already_acknowledged", "work_order_id": str(wo_id)}
        
        # Validate transition
        if wo.status not in ["GENERATED"]:
            raise InvalidTransitionError(f"Cannot acknowledge from {wo.status}")
        
        wo.status = "ACKNOWLEDGED"
        wo.acknowledged_at = utcnow()
        wo.viewed_by = ctx.user_id
        wo.first_view_at = wo.acknowledged_at
        
        await session.commit()
        
        await publish("work_order.acknowledged", {
            "work_order_id": str(wo_id),
            "acknowledged_by": str(ctx.user_id),
        })
        
        logger.info(f"Work order {wo_id} acknowledged by {ctx.user_id}")
        return {"status": "acknowledged", "work_order_id": str(wo_id)}


async def reject(ctx: RequestContext, wo_id: UUID, reason: str) -> Dict[str, Any]:
    """Reject a work order."""
    session_factory = await get_service("db", "DatabasePort")
    notify = await get_service("notify", "NotifyPort", optional=True)
    
    async with session_factory.org_scoped_session(ctx.org_id) as session:
        wo = await session.get(WorkOrder, wo_id)
        if not wo or wo.organization_id != ctx.org_id:
            raise NotFoundError("Work order not found")
        
        if wo.status not in ["GENERATED", "ACKNOWLEDGED", "IN_PROGRESS", "SNOOZED"]:
            raise InvalidTransitionError(f"Cannot reject from {wo.status}")
        
        wo.status = "REJECTED"
        
        # Record rejection
        rejection = RejectionRecord(
            work_order_id=wo_id,
            reason=reason,
            rejected_by=ctx.user_id,
        )
        session.add(rejection)
        
        await session.commit()
        
        await publish("work_order.rejected", {
            "work_order_id": str(wo_id),
            "rejected_by": str(ctx.user_id),
            "reason": reason,
        })
        
        # Notify manager
        if notify:
            await notify.notify_role(
                org_id=ctx.org_id,
                role="MANAGER",
                event="work_order.rejected",
                data={"work_order_id": str(wo_id), "reason": reason}
            )
        
        logger.info(f"Work order {wo_id} rejected by {ctx.user_id}: {reason}")
        return {"status": "rejected", "work_order_id": str(wo_id)}


async def snooze(ctx: RequestContext, wo_id: UUID, duration: str, reason: str) -> Dict[str, Any]:
    """Snooze a work order."""
    session_factory = await get_service("db", "DatabasePort")
    cache = await get_service("cache", "CachePort", optional=True)
    
    valid_durations = {"1h", "6h", "12h", "1d", "3d", "6d"}
    if duration not in valid_durations:
        raise DomainError(f"Invalid snooze duration. Must be one of: {valid_durations}")
    
    # Calculate resume time
    now = utcnow()
    hours_map = {"1h": 1, "6h": 6, "12h": 12, "1d": 24, "3d": 72, "6d": 144}
    resume_at = now + timedelta(hours=hours_map[duration])
    
    async with session_factory.org_scoped_session(ctx.org_id) as session:
        wo = await session.get(WorkOrder, wo_id)
        if not wo or wo.organization_id != ctx.org_id:
            raise NotFoundError("Work order not found")
        
        if wo.status not in ["GENERATED", "ACKNOWLEDGED", "IN_PROGRESS"]:
            raise InvalidTransitionError(f"Cannot snooze from {wo.status}")
        
        previous_status = wo.status
        wo.status = "SNOOZED"
        
        # Record snooze
        snooze_rec = SnoozeRecord(
            work_order_id=wo_id,
            duration=duration,
            reason=reason,
            snoozed_by=ctx.user_id,
            resume_at=resume_at,
            previous_status=previous_status,
        )
        session.add(snooze_rec)
        
        # Schedule resume via cache delay queue
        if cache:
            await cache.delay_schedule(
                "workorders.resume_snoozed_task",
                {"work_order_id": str(wo_id)},
                run_at=resume_at
            )
        
        await session.commit()
        
        await publish("work_order.snoozed", {
            "work_order_id": str(wo_id),
            "snoozed_by": str(ctx.user_id),
            "duration": duration,
            "resume_at": resume_at.isoformat(),
        })
        
        logger.info(f"Work order {wo_id} snoozed for {duration} by {ctx.user_id}")
        return {"status": "snoozed", "work_order_id": str(wo_id), "resume_at": resume_at.isoformat()}


async def resume(ctx: RequestContext, wo_id: UUID) -> Dict[str, Any]:
    """Resume a snoozed work order."""
    session_factory = await get_service("db", "DatabasePort")
    
    async with session_factory.org_scoped_session(ctx.org_id) as session:
        wo = await session.get(WorkOrder, wo_id)
        if not wo or wo.organization_id != ctx.org_id:
            raise NotFoundError("Work order not found")
        
        if wo.status != "SNOOZED":
            raise InvalidTransitionError(f"Cannot resume from {wo.status}")
        
        # Find latest snooze record
        snooze_rec = max(wo.snooze_records, key=lambda s: s.snoozed_at)
        wo.status = snooze_rec.previous_status
        snooze_rec.resumed_at = utcnow()
        
        await session.commit()
        
        await publish("work_order.resumed", {
            "work_order_id": str(wo_id),
            "resumed_by": str(ctx.user_id),
        })
        
        logger.info(f"Work order {wo_id} resumed by {ctx.user_id}")
        return {"status": "resumed", "work_order_id": str(wo_id)}


async def update_item(
    ctx: RequestContext, 
    wo_id: UUID, 
    item_id: str, 
    patch: ItemUpdate
) -> Dict[str, Any]:
    """Update a work order item."""
    session_factory = await get_service("db", "DatabasePort")
    
    async with session_factory.org_scoped_session(ctx.org_id) as session:
        wo = await session.get(WorkOrder, wo_id)
        if not wo or wo.organization_id != ctx.org_id:
            raise NotFoundError("Work order not found")
        
        # Find item
        item = next((i for i in wo.items if i.id == item_id), None)
        if not item:
            raise NotFoundError("Item not found")
        
        # Validate role
        if ctx.role not in ["MAINTENANCE", "MANAGER"]:
            raise ForbiddenError("Only MAINTENANCE or MANAGER can update items")
        
        # Apply updates
        if patch.status:
            # Validate predecessor logic
            if patch.status == "PENDING_PREDECESSOR" and item.predecessor:
                # Check if predecessor is complete
                pred_item = next((i for i in wo.items if i.id == item.predecessor), None)
                if pred_item and pred_item.status not in ["COMPLETED", "FAILED"]:
                    item.status = "PENDING_PREDECESSOR"
                else:
                    item.status = patch.status.value if isinstance(patch.status, ItemStatus) else patch.status
            else:
                item.status = patch.status.value if isinstance(patch.status, ItemStatus) else patch.status
        
        if patch.notes:
            item.notes = patch.notes
        if patch.started_at:
            item.started_at = patch.started_at
        if patch.closed_at:
            item.closed_at = patch.closed_at
        if patch.performed_by:
            item.performed_by = patch.performed_by
        
        # Recompute completion percentage
        new_completion = recompute_completion(wo_id)
        wo.completion_percentage = new_completion
        
        await session.commit()
        
        await publish("wo_item.updated", {
            "work_order_id": str(wo_id),
            "item_id": item_id,
            "updated_by": str(ctx.user_id),
        })
        
        return {"status": "updated", "item_id": item_id, "completion_percentage": new_completion}


async def record_measurement(
    ctx: RequestContext,
    wo_id: UUID,
    item_id: str,
    value: Any
) -> Dict[str, Any]:
    """Record a measurement for a work item."""
    session_factory = await get_service("db", "DatabasePort")
    
    async with session_factory.org_scoped_session(ctx.org_id) as session:
        wo = await session.get(WorkOrder, wo_id)
        if not wo or wo.organization_id != ctx.org_id:
            raise NotFoundError("Work order not found")
        
        item = next((i for i in wo.items if i.id == item_id), None)
        if not item:
            raise NotFoundError("Item not found")
        
        # Type-check against snapshot definition
        if item.measurement_fields:
            # For simplicity, assume single measurement field
            mf = item.measurement_fields[0] if item.measurement_fields else None
            if mf:
                # Auto pass/fail from thresholds (post-MVP)
                passed = None
                if isinstance(value, (int, float)):
                    if mf.get("lower_threshold") and value < mf["lower_threshold"]:
                        passed = False
                    if mf.get("upper_threshold") and value > mf["upper_threshold"]:
                        passed = False
                    if passed is None:
                        passed = True
        
        measurement = WorkOrderItemMeasurement(
            work_order_id=wo_id,
            item_id=item_id,
            field_name=item.measurement_fields[0]["name"] if item.measurement_fields else "value",
            value=value,
            recorded_by=ctx.user_id,
            passed=passed,
        )
        session.add(measurement)
        
        await session.commit()
        
        await publish("wo_item.measured", {
            "work_order_id": str(wo_id),
            "item_id": item_id,
            "recorded_by": str(ctx.user_id),
        })
        
        return {"status": "measured", "value": value, "passed": passed}


async def add_comment(
    ctx: RequestContext,
    wo_id: UUID,
    text: str,
    parent_comment_id: Optional[str] = None
) -> Dict[str, Any]:
    """Add a comment to a work order."""
    session_factory = await get_service("db", "DatabasePort")
    
    async with session_factory.org_scoped_session(ctx.org_id) as session:
        wo = await session.get(WorkOrder, wo_id)
        if not wo or wo.organization_id != ctx.org_id:
            raise NotFoundError("Work order not found")
        
        comment = WorkOrderComment(
            work_order_id=wo_id,
            parent_comment_id=parent_comment_id,
            text=text,
            created_by=ctx.user_id,
        )
        session.add(comment)
        await session.commit()
        
        return {"status": "commented", "comment_id": comment.id}


async def attach_file(
    ctx: RequestContext,
    wo_id: UUID,
    file_id: UUID,
    item_id: Optional[str] = None
) -> Dict[str, Any]:
    """Attach a file to a work order or item."""
    session_factory = await get_service("db", "DatabasePort")
    files = await get_service("files", "FilesPort", optional=True)
    
    async with session_factory.org_scoped_session(ctx.org_id) as session:
        wo = await session.get(WorkOrder, wo_id)
        if not wo or wo.organization_id != ctx.org_id:
            raise NotFoundError("Work order not found")
        
        # Verify file access via FILES module
        if files:
            await files.verify_access(ctx.org_id, file_id)
        
        attachment = WorkOrderAttachment(
            work_order_id=wo_id,
            item_id=item_id,
            file_id=file_id,
            attached_by=ctx.user_id,
        )
        session.add(attachment)
        await session.commit()
        
        return {"status": "attached", "file_id": str(file_id)}


async def sign(
    ctx: RequestContext,
    wo_id: UUID,
    item_id: str,
    signature: str
) -> Dict[str, Any]:
    """Add digital signature to a work item."""
    session_factory = await get_service("db", "DatabasePort")
    
    async with session_factory.org_scoped_session(ctx.org_id) as session:
        wo = await session.get(WorkOrder, wo_id)
        if not wo or wo.organization_id != ctx.org_id:
            raise NotFoundError("Work order not found")
        
        item = next((i for i in wo.items if i.id == item_id), None)
        if not item:
            raise NotFoundError("Item not found")
        
        if not item.signature_required:
            raise DomainError("Signature not required for this item")
        
        sig = WorkOrderSignature(
            work_order_id=wo_id,
            item_id=item_id,
            signer_id=ctx.user_id,
            signature_data=signature,
        )
        session.add(sig)
        await session.commit()
        
        await publish("wo_item.signed", {
            "work_order_id": str(wo_id),
            "item_id": item_id,
            "signed_by": str(ctx.user_id),
        })
        
        return {"status": "signed", "item_id": item_id}


async def complete(
    ctx: RequestContext,
    wo_id: UUID,
    cost: Optional[float] = None,
    downtime: Optional[int] = None
) -> Dict[str, Any]:
    """Complete a work order."""
    session_factory = await get_service("db", "DatabasePort")
    assets = await get_service("assets", "AssetsPort", optional=True)
    
    async with session_factory.org_scoped_session(ctx.org_id) as session:
        wo = await session.get(WorkOrder, wo_id)
        if not wo or wo.organization_id != ctx.org_id:
            raise NotFoundError("Work order not found")
        
        # Validate all items are terminal
        for item in wo.items:
            if item.status not in ["COMPLETED", "FAILED", "PENDING_PREDECESSOR"]:
                raise DomainError(f"Cannot complete: item {item.id} is not terminal ({item.status})")
        
        if wo.completion_percentage != 100:
            raise DomainError("Cannot complete: work order not 100% complete")
        
        wo.status = "COMPLETED"
        wo.completed_at = utcnow()
        wo.cost = cost
        wo.downtime = downtime
        
        await session.commit()
        
        # Release STOP_UNTIL_COMPLETE effects via ASSETS
        if assets and wo.safety_flag == "STOP_UNTIL_COMPLETE":
            await assets.clear_safety_flag(wo.target_entity_id, wo.safety_flag)
        
        await publish("work_order.completed", {
            "work_order_id": str(wo_id),
            "completed_by": str(ctx.user_id),
            "cost": cost,
            "downtime": downtime,
        })
        
        logger.info(f"Work order {wo_id} completed by {ctx.user_id}")
        return {"status": "completed", "work_order_id": str(wo_id)}


async def close_wo(
    ctx: RequestContext,
    wo_id: UUID,
    quality_check_by: Optional[str] = None
) -> Dict[str, Any]:
    """Close a work order (MANAGER only)."""
    session_factory = await get_service("db", "DatabasePort")
    
    async with session_factory.org_scoped_session(ctx.org_id) as session:
        wo = await session.get(WorkOrder, wo_id)
        if not wo or wo.organization_id != ctx.org_id:
            raise NotFoundError("Work order not found")
        
        if wo.status != "COMPLETED":
            raise InvalidTransitionError(f"Cannot close from {wo.status}")
        
        if ctx.role not in ["MANAGER", "SYS_ADMIN"]:
            raise ForbiddenError("Only MANAGER or SYS_ADMIN can close work orders")
        
        wo.status = "CLOSED"
        wo.closed_at = utcnow()
        wo.closed_by = ctx.user_id
        wo.quality_check_by = quality_check_by
        
        await session.commit()
        
        await publish("work_order.closed", {
            "work_order_id": str(wo_id),
            "closed_by": str(ctx.user_id),
        })
        
        logger.info(f"Work order {wo_id} closed by {ctx.user_id}")
        return {"status": "closed", "work_order_id": str(wo_id)}


def recompute_completion(wo_id: UUID) -> int:
    """Recompute completion percentage from item states."""
    # This would normally query the database
    # Simplified implementation
    return 0


async def _on_cycle_due(payload: Dict[str, Any]) -> None:
    """Handle cycle.due event."""
    cycle_id = payload.get("cycle_id")
    trigger_ctx = payload.get("trigger_ctx", {})
    
    try:
        await generate_from_cycle(UUID(cycle_id), trigger_ctx)
    except Exception as e:
        logger.error(f"Failed to generate work order from cycle.due: {e}")
        await publish("work_order.gen_failed", {
            "cycle_id": cycle_id,
            "error": str(e),
        })


async def _on_cycle_missed(payload: Dict[str, Any]) -> None:
    """Handle cycle.missed event."""
    cycle_id = payload.get("cycle_id")
    trigger_ctx = payload.get("trigger_ctx", {})
    trigger_ctx["source"] = "MISSED"
    trigger_ctx["overdue"] = True
    
    try:
        await generate_from_cycle(UUID(cycle_id), trigger_ctx)
    except Exception as e:
        logger.error(f"Failed to generate work order from cycle.missed: {e}")


# Worker task: resume snoozed work orders
async def resume_snoozed_task(work_order_id: str) -> None:
    """Resume a snoozed work order (called by worker)."""
    # This would be registered with the worker module
    logger.info(f"Resuming snoozed work order {work_order_id}")
    # Implementation would call resume() function


# Worker task: flag overdue work orders
async def flag_overdue_task() -> None:
    """Flag overdue work orders (beat task every 5 minutes)."""
    session_factory = await get_service("db", "DatabasePort")
    notify = await get_service("notify", "NotifyPort", optional=True)
    
    now = utcnow()
    
    async with session_factory.session_factory()() as session:
        # Find active WOs past deadline
        stmt = select(WorkOrder).where(
            WorkOrder.status.in_(["GENERATED", "ACKNOWLEDGED", "IN_PROGRESS", "SNOOZED"]),
            WorkOrder.deadline < now,
            WorkOrder.has_overdue_flag == False,
            WorkOrder.deleted_at.is_(None)
        )
        results = await session.execute(stmt)
        overdue_wos = results.scalars().all()
        
        for wo in overdue_wos:
            wo.has_overdue_flag = True
            wo.status = "OVERDUE"
            
            # Apply deadline_behavior
            if wo.deadline_behavior == "FLAG_CRITICAL_STOP":
                # Trigger ASSETS safety flag
                if assets := await get_service("assets", "AssetsPort", optional=True):
                    await assets.set_safety_flag(
                        wo.target_entity_id,
                        "CRITICAL_STOP",
                        f"Work order {wo.code} overdue"
                    )
            
            await publish("work_order.overdue", {
                "work_order_id": str(wo.id),
                "code": wo.code,
            })
            
            if notify:
                await notify.notify_role(
                    org_id=wo.organization_id,
                    role="MANAGER",
                    event="work_order.overdue",
                    data={"work_order_id": str(wo.id), "code": wo.code}
                )
        
        await session.commit()
        logger.info(f"Flagged {len(overdue_wos)} overdue work orders")
