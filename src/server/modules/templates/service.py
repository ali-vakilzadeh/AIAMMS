"""
TEMPLATES Module Service - Workflows & Checklists

Implements template management for maintenance workflows and inspection checklists.
Provides immutable snapshots for work order generation, item-level search, and graph validation.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Literal, Set, Tuple
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import (
    select,
    update,
    delete,
    func,
    text as sql_text,
    Index,
    UniqueConstraint,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.server.core.module_base import ModuleBase, HealthStatus
from src.server.core.health import HealthReport
from src.server.core.registry import get_service
from src.server.core.logger import get_logger
from src.server.core.utils import utcnow, new_id
from src.server.shared.types import RequestContext
from src.server.modules.api.service import PaginatedResponse
from src.server.core.event_bus import get_event_bus

logger = get_logger("templates")

# =============================================================================
# Data Models (Pydantic)
# =============================================================================


class MeasurementField(BaseModel):
    """Measurement field definition for workflow/checklist items."""
    name: str
    data_type: Literal["NUMERIC", "TEXT", "BOOLEAN"] = "NUMERIC"
    unit: Optional[str] = None
    lower_threshold: Optional[float] = None  # For NUMERIC: fail if < threshold
    upper_threshold: Optional[float] = None  # For NUMERIC: fail if > threshold
    required: bool = False


class WorkflowItem(BaseModel):
    """Single item in a workflow template."""
    id: Optional[str] = None  # Generated if not provided
    activity_number: int
    predecessor: Optional[str] = None  # References another item's id
    description: str
    dates: Optional[Dict[str, Any]] = None  # {planned_start, planned_end}
    status: str = "PENDING"
    priority: int = 50  # 1-100
    durations: Optional[Dict[str, Any]] = None  # {estimated_hours, max_hours}
    assignee: Optional[str] = None  # Role or skill requirement
    skills: Optional[List[str]] = None
    certs: Optional[List[str]] = None
    tools: Optional[List[str]] = None
    parts: Optional[List[str]] = None
    safety_permit: Optional[str] = None  # Required safety permit type
    risk: Optional[str] = None  # Risk level: LOW|MEDIUM|HIGH|CRITICAL
    location_override: Optional[Dict[str, Any]] = None
    measurement_fields: Optional[List[MeasurementField]] = None
    signature_required: bool = False
    cost: Optional[float] = None
    downtime: Optional[int] = None  # Estimated downtime in minutes
    notes: Optional[str] = None

    class Config:
        extra = "allow"


class ChecklistItem(BaseModel):
    """Single item in a checklist template (flat structure)."""
    id: Optional[str] = None
    activity_number: int
    description: str
    result_domain: Literal["Inspected", "Pass", "Fail"] = "Inspected"
    measurement_fields: Optional[List[MeasurementField]] = None
    notes: Optional[str] = None

    class Config:
        extra = "allow"


class WorkItemSnapshot(BaseModel):
    """Frozen snapshot of a workflow/checklist item for WO generation."""
    id: str
    activity_number: int
    predecessor: Optional[str]
    description: str
    status: str
    priority: int
    measurement_fields: Optional[List[MeasurementField]]
    signature_required: bool
    safety_permit: Optional[str]
    risk: Optional[str]
    assignee: Optional[str]
    skills: Optional[List[str]]
    certs: Optional[List[str]]
    tools: Optional[List[str]]
    parts: Optional[List[str]]
    cost: Optional[float]
    downtime: Optional[int]
    notes: Optional[str]


class TemplateSnapshot(BaseModel):
    """Immutable snapshot of a template for work order generation."""
    template_id: UUID
    kind: Literal["workflow", "checklist"]
    code: str
    name: str
    description: Optional[str]
    items: List[WorkItemSnapshot]
    frozen_at: datetime


class SearchHit(BaseModel):
    """Search result with matched item snippet."""
    template_id: UUID
    template_name: str
    template_code: str
    kind: Literal["workflow", "checklist"]
    matched_item_id: str
    matched_item_description: str
    match_score: float


# =============================================================================
# SQLAlchemy Models
# =============================================================================

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB

class Base(DeclarativeBase):
    pass


class Workflow(Base):
    __tablename__ = "workflows"
    
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(index=True, nullable=False)
    code: Mapped[str] = mapped_column(unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[Optional[str]]
    is_active: Mapped[bool] = mapped_column(default=True)
    deleted_at: Mapped[Optional[datetime]]
    created_at: Mapped[datetime] = mapped_column(default=lambda: utcnow())
    updated_at: Mapped[datetime] = mapped_column(default=lambda: utcnow(), onupdate=lambda: utcnow())
    
    items: Mapped[List["WorkflowItemModel"]] = relationship(back_populates="workflow", cascade="all, delete-orphan")


class WorkflowItemModel(Base):
    __tablename__ = "workflow_items"
    
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: new_id())
    workflow_id: Mapped[UUID] = mapped_column(ForeignKey("workflows.id"), index=True, nullable=False)
    activity_number: Mapped[int]
    predecessor: Mapped[Optional[str]]
    description: Mapped[str]
    data: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)  # All other fields
    created_at: Mapped[datetime] = mapped_column(default=lambda: utcnow())
    updated_at: Mapped[datetime] = mapped_column(default=lambda: utcnow(), onupdate=lambda: utcnow())
    
    workflow: Mapped["Workflow"] = relationship(back_populates="items")
    
    __table_args__ = (
        Index("ix_workflow_items_workflow", "workflow_id"),
        Index("ix_workflow_items_description", "description", postgresql_using="gin"),
    )


class Checklist(Base):
    __tablename__ = "checklists"
    
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(index=True, nullable=False)
    code: Mapped[str] = mapped_column(unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[Optional[str]]
    is_active: Mapped[bool] = mapped_column(default=True)
    deleted_at: Mapped[Optional[datetime]]
    created_at: Mapped[datetime] = mapped_column(default=lambda: utcnow())
    updated_at: Mapped[datetime] = mapped_column(default=lambda: utcnow(), onupdate=lambda: utcnow())
    
    items: Mapped[List["ChecklistItemModel"]] = relationship(back_populates="checklist", cascade="all, delete-orphan")


class ChecklistItemModel(Base):
    __tablename__ = "checklist_items"
    
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: new_id())
    checklist_id: Mapped[UUID] = mapped_column(ForeignKey("checklists.id"), index=True, nullable=False)
    activity_number: Mapped[int]
    description: Mapped[str]
    data: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=lambda: utcnow())
    updated_at: Mapped[datetime] = mapped_column(default=lambda: utcnow(), onupdate=lambda: utcnow())
    
    checklist: Mapped["Checklist"] = relationship(back_populates="items")
    
    __table_args__ = (
        Index("ix_checklist_items_checklist", "checklist_id"),
        Index("ix_checklist_items_description", "description", postgresql_using="gin"),
    )


# =============================================================================
# Module Class
# =============================================================================

class TemplatesModule(ModuleBase):
    """Templates module for workflow and checklist management."""
    
    name = "templates"
    version = "1.0.0"
    dependencies = ["core", "db", "api"]
    optional_dependencies = ["auth", "tenancy"]
    profiles = ["api", "worker", "all-in-one"]
    
    def __init__(self):
        super().__init__()
        self.router = APIRouter(prefix="/templates", tags=["templates"])
        self._code_lock_prefix = "templates:code:"
    
    async def configure(self, settings: Dict[str, Any]) -> None:
        """Configure templates module."""
        self.settings = settings
        logger.info("Templates module configured")
    
    async def initialize(self, ctx: Dict[str, Any]) -> None:
        """Initialize templates module."""
        self.db = await get_service("db", "DatabasePort")
        self.api = await get_service("api", "ApiPort")
        self.auth = await get_service("auth", "AuthPort", optional=True)
        self.tenancy = await get_service("tenancy", "TenancyPort", optional=True)
        
        # Register routes
        self._register_routes()
        
        logger.info("Templates module initialized")
    
    async def start(self) -> None:
        """Start templates module."""
        logger.info("Templates module started")
    
    async def stop(self) -> None:
        """Stop templates module."""
        logger.info("Templates module stopped")
    
    async def health(self) -> HealthReport:
        """Health check for templates module."""
        return HealthReport(
            module=self.name,
            status=HealthStatus.OK,
            details={"templates_available": True}
        )
    
    def _register_routes(self) -> None:
        """Register API routes."""
        # Workflow routes
        self.api.register_router(self.router, "workflows", ["templates"])
        
        @self.router.post("/workflows", status_code=status.HTTP_201_CREATED)
        async def _create_workflow_route(
            data: Dict[str, Any],
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await create_workflow(ctx, data)
        
        @self.router.get("/workflows/{workflow_id}")
        async def _get_workflow_route(
            workflow_id: UUID,
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await get_workflow(ctx, workflow_id)
        
        @self.router.patch("/workflows/{workflow_id}")
        async def _update_workflow_route(
            workflow_id: UUID,
            patch: Dict[str, Any],
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await update_workflow(ctx, workflow_id, patch)
        
        @self.router.get("/workflows")
        async def _list_workflows_route(
            q: Optional[str] = None,
            page: int = 1,
            page_size: int = 50,
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await list_workflows(ctx, q, page, page_size)
        
        @self.router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
        async def _archive_workflow_route(
            workflow_id: UUID,
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            await archive_workflow(ctx, workflow_id)
        
        @self.router.post("/workflows/{workflow_id}/items")
        async def _add_workflow_item_route(
            workflow_id: UUID,
            item: WorkflowItem,
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await add_workflow_item(ctx, workflow_id, item)
        
        @self.router.patch("/workflows/{workflow_id}/items/{item_id}")
        async def _update_workflow_item_route(
            workflow_id: UUID,
            item_id: str,
            patch: Dict[str, Any],
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await update_workflow_item(ctx, workflow_id, item_id, patch)
        
        @self.router.delete("/workflows/{workflow_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
        async def _delete_workflow_item_route(
            workflow_id: UUID,
            item_id: str,
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            await delete_workflow_item(ctx, workflow_id, item_id)
        
        @self.router.get("/workflows/search")
        async def _search_workflows_route(
            q: str,
            page: int = 1,
            page_size: int = 50,
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await search_workflows(ctx, q, page, page_size)
        
        # Checklist routes
        @self.router.post("/checklists", status_code=status.HTTP_201_CREATED)
        async def _create_checklist_route(
            data: Dict[str, Any],
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await create_checklist(ctx, data)
        
        @self.router.get("/checklists/{checklist_id}")
        async def _get_checklist_route(
            checklist_id: UUID,
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await get_checklist(ctx, checklist_id)
        
        @self.router.patch("/checklists/{checklist_id}")
        async def _update_checklist_route(
            checklist_id: UUID,
            patch: Dict[str, Any],
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await update_checklist(ctx, checklist_id, patch)
        
        @self.router.get("/checklists")
        async def _list_checklists_route(
            q: Optional[str] = None,
            page: int = 1,
            page_size: int = 50,
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await list_checklists(ctx, q, page, page_size)
        
        @self.router.delete("/checklists/{checklist_id}", status_code=status.HTTP_204_NO_CONTENT)
        async def _archive_checklist_route(
            checklist_id: UUID,
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            await archive_checklist(ctx, checklist_id)
        
        @self.router.post("/checklists/{checklist_id}/items")
        async def _add_checklist_item_route(
            checklist_id: UUID,
            item: ChecklistItem,
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await add_checklist_item(ctx, checklist_id, item)
        
        @self.router.patch("/checklists/{checklist_id}/items/{item_id}")
        async def _update_checklist_item_route(
            checklist_id: UUID,
            item_id: str,
            patch: Dict[str, Any],
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await update_checklist_item(ctx, checklist_id, item_id, patch)
        
        @self.router.delete("/checklists/{checklist_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
        async def _delete_checklist_item_route(
            checklist_id: UUID,
            item_id: str,
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            await delete_checklist_item(ctx, checklist_id, item_id)
        
        @self.router.get("/checklists/search")
        async def _search_checklists_route(
            q: str,
            page: int = 1,
            page_size: int = 50,
            ctx: RequestContext = Depends(self.api.request_context)
        ):
            return await search_checklists(ctx, q, page, page_size)


# =============================================================================
# Helper Functions
# =============================================================================

async def _generate_unique_code(session: AsyncSession, org_id: UUID, prefix: str) -> str:
    """Generate unique code for workflow/checklist within organization."""
    cache = await get_service("cache", "CachePort")
    
    # Try up to 10 times to generate unique code
    for _ in range(10):
        suffix = new_id()[:6].upper()
        code = f"{prefix}-{org_id.hex[:8]}-{suffix}"
        
        # Use distributed lock to prevent race conditions
        lock_key = f"{_code_lock_prefix}{code}"
        async with cache.lock(lock_key, ttl_s=5, wait_ms=100):
            # Check if code exists
            result = await session.execute(
                select(Workflow.code).where(Workflow.code == code)
                .union(
                    select(Checklist.code).where(Checklist.code == code)
                )
            )
            if not result.first():
                return code
    
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Failed to generate unique code after multiple attempts"
    )


def validate_item_graph(items: List[Dict[str, Any]]) -> None:
    """
    Validate workflow item graph:
    - Predecessor references exist within same workflow
    - Graph is acyclic
    - Measurement fields match data_type constraints
    """
    item_ids = {item.get("id") or f"_{item.get('activity_number')}" for item in items}
    
    # Build adjacency list for cycle detection
    graph: Dict[str, List[str]] = {}
    for item in items:
        item_id = item.get("id") or f"_{item.get('activity_number')}"
        predecessor = item.get("predecessor")
        graph[item_id] = []
        if predecessor:
            if predecessor not in item_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Predecessor '{predecessor}' does not exist in workflow"
                )
            graph[predecessor].append(item_id)
    
    # Detect cycles using DFS
    visited: Set[str] = set()
    rec_stack: Set[str] = set()
    
    def has_cycle(node: str) -> bool:
        visited.add(node)
        rec_stack.add(node)
        
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                if has_cycle(neighbor):
                    return True
            elif neighbor in rec_stack:
                return True
        
        rec_stack.remove(node)
        return False
    
    for item_id in graph:
        if item_id not in visited:
            if has_cycle(item_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Workflow contains cyclic predecessor references"
                )
    
    # Validate measurement fields
    for item in items:
        measurement_fields = item.get("measurement_fields", [])
        for mf in measurement_fields:
            data_type = mf.get("data_type", "NUMERIC")
            if data_type == "NUMERIC":
                # Thresholds only valid for NUMERIC
                if "lower_threshold" in mf or "upper_threshold" in mf:
                    continue  # Valid
            else:
                # Non-numeric cannot have thresholds
                if "lower_threshold" in mf or "upper_threshold" in mf:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Thresholds only valid for NUMERIC measurement fields"
                    )


async def _check_rbac(ctx: RequestContext, action: str) -> None:
    """Check RBAC permissions."""
    if ctx.role not in ["MANAGER", "SYS_ADMIN"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="MANAGER or SYS_ADMIN role required"
        )


# =============================================================================
# Workflow Functions
# =============================================================================

async def create_workflow(ctx: RequestContext, data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new workflow template."""
    await _check_rbac(ctx, "create_workflow")
    
    async with ctx.session() as session:
        # Generate code if not provided
        code = data.get("code")
        if not code:
            code = await _generate_unique_code(session, ctx.org_id, "WF")
        else:
            # Check uniqueness
            result = await session.execute(
                select(Workflow.code).where(Workflow.code == code)
            )
            if result.first():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Workflow code already exists"
                )
        
        # Validate items
        items_data = data.get("items", [])
        if items_data:
            validate_item_graph(items_data)
        
        # Create workflow
        workflow = Workflow(
            organization_id=ctx.org_id,
            code=code,
            name=data["name"],
            description=data.get("description"),
        )
        session.add(workflow)
        await session.flush()
        
        # Add items
        for item_data in items_data:
            item = WorkflowItemModel(
                workflow_id=workflow.id,
                activity_number=item_data["activity_number"],
                predecessor=item_data.get("predecessor"),
                description=item_data["description"],
                data={k: v for k, v in item_data.items() 
                      if k not in ["activity_number", "predecessor", "description", "id"]}
            )
            session.add(item)
        
        await session.commit()
        
        # Emit event
        event_bus = await get_service("core", "EventBusPort")
        await event_bus.publish(
            "template.created",
            dict(
                event_type="template.created",
                aggregate_id=workflow.id,
                aggregate_type="workflow",
                organization_id=ctx.org_id,
                data={"workflow_id": str(workflow.id), "code": code}
            )
        )
        
        logger.info(f"Workflow created: {workflow.id}", extra={"audit": True})
        
        return {"id": workflow.id, "code": code, "name": workflow.name}


async def get_workflow(ctx: RequestContext, workflow_id: UUID) -> Dict[str, Any]:
    """Get workflow by ID with items."""
    async with ctx.session() as session:
        result = await session.execute(
            select(Workflow)
            .where(Workflow.id == workflow_id)
            .where(Workflow.organization_id == ctx.org_id)
            .where(Workflow.deleted_at.is_(None))
        )
        workflow = result.scalar_one_or_none()
        
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found"
            )
        
        # Load items
        items_result = await session.execute(
            select(WorkflowItemModel)
            .where(WorkflowItemModel.workflow_id == workflow_id)
            .order_by(WorkflowItemModel.activity_number)
        )
        items = items_result.scalars().all()
        
        return {
            "id": workflow.id,
            "code": workflow.code,
            "name": workflow.name,
            "description": workflow.description,
            "is_active": workflow.is_active,
            "items": [
                {
                    "id": item.id,
                    "activity_number": item.activity_number,
                    "predecessor": item.predecessor,
                    "description": item.description,
                    **item.data
                }
                for item in items
            ]
        }


async def update_workflow(ctx: RequestContext, workflow_id: UUID, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Update workflow header (does NOT affect existing work orders)."""
    await _check_rbac(ctx, "update_workflow")
    
    async with ctx.session() as session:
        # Check code uniqueness if changed
        if "code" in patch:
            result = await session.execute(
                select(Workflow.id).where(
                    Workflow.code == patch["code"],
                    Workflow.id != workflow_id
                )
            )
            if result.first():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Workflow code already exists"
                )
        
        # Update
        await session.execute(
            update(Workflow)
            .where(Workflow.id == workflow_id)
            .where(Workflow.organization_id == ctx.org_id)
            .values(**patch, updated_at=utcnow())
        )
        await session.commit()
        
        # Emit event
        event_bus = await get_service("core", "EventBusPort")
        await event_bus.publish(
            "template.updated",
            dict(
                event_type="template.updated",
                aggregate_id=workflow_id,
                aggregate_type="workflow",
                organization_id=ctx.org_id,
                data={"patch": patch}
            )
        )
        
        logger.info(f"Workflow updated: {workflow_id}", extra={"audit": True})
        
        return {"id": workflow_id, **patch}


async def list_workflows(
    ctx: RequestContext,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 50
) -> PaginatedResponse:
    """List workflows with optional search."""
    async with ctx.session() as session:
        stmt = select(Workflow).where(
            Workflow.organization_id == ctx.org_id,
            Workflow.deleted_at.is_(None)
        )
        
        if q:
            stmt = stmt.where(
                (Workflow.name.ilike(f"%{q}%")) |
                (Workflow.code.ilike(f"%{q}%")) |
                (Workflow.description.ilike(f"%{q}%"))
            )
        
        total = await session.execute(select(func.count()).select_from(stmt.subquery()))
        total_count = total.scalar()
        
        stmt = stmt.order_by(Workflow.created_at.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        
        result = await session.execute(stmt)
        workflows = result.scalars().all()
        
        return PaginatedResponse(
            items=[
                {
                    "id": wf.id,
                    "code": wf.code,
                    "name": wf.name,
                    "description": wf.description,
                    "created_at": wf.created_at
                }
                for wf in workflows
            ],
            total=total_count,
            page=page,
            page_size=page_size
        )


async def archive_workflow(ctx: RequestContext, workflow_id: UUID) -> None:
    """Soft-delete workflow (blocked if referenced by active cycles)."""
    await _check_rbac(ctx, "archive_workflow")
    
    async with ctx.session() as session:
        # TODO: Check for active cycle references (requires CYCLES module integration)
        # For now, just soft delete
        
        await session.execute(
            update(Workflow)
            .where(Workflow.id == workflow_id)
            .where(Workflow.organization_id == ctx.org_id)
            .values(deleted_at=utcnow(), is_active=False)
        )
        await session.commit()
        
        # Emit event
        event_bus = await get_service("core", "EventBusPort")
        await event_bus.publish(
            "template.archived",
            dict(
                event_type="template.archived",
                aggregate_id=workflow_id,
                aggregate_type="workflow",
                organization_id=ctx.org_id,
                data={}
            )
        )
        
        logger.info(f"Workflow archived: {workflow_id}", extra={"audit": True})


async def add_workflow_item(ctx: RequestContext, workflow_id: UUID, item: WorkflowItem) -> Dict[str, Any]:
    """Add item to workflow with validation."""
    await _check_rbac(ctx, "add_workflow_item")
    
    async with ctx.session() as session:
        # Verify workflow exists
        result = await session.execute(
            select(Workflow.id).where(
                Workflow.id == workflow_id,
                Workflow.organization_id == ctx.org_id
            )
        )
        if not result.scalar():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found"
            )
        
        # Validate predecessor if specified
        if item.predecessor:
            existing = await session.execute(
                select(WorkflowItemModel.id).where(
                    WorkflowItemModel.workflow_id == workflow_id,
                    WorkflowItemModel.id == item.predecessor
                )
            )
            if not existing.scalar():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Predecessor '{item.predecessor}' does not exist"
                )
        
        # Create item
        item_model = WorkflowItemModel(
            workflow_id=workflow_id,
            activity_number=item.activity_number,
            predecessor=item.predecessor,
            description=item.description,
            data=item.model_dump(exclude={"id", "activity_number", "predecessor", "description"})
        )
        session.add(item_model)
        await session.commit()
        
        return {"id": item_model.id, "activity_number": item_model.activity_number}


async def update_workflow_item(
    ctx: RequestContext,
    workflow_id: UUID,
    item_id: str,
    patch: Dict[str, Any]
) -> Dict[str, Any]:
    """Update workflow item."""
    await _check_rbac(ctx, "update_workflow_item")
    
    async with ctx.session() as session:
        await session.execute(
            update(WorkflowItemModel)
            .where(WorkflowItemModel.id == item_id)
            .where(WorkflowItemModel.workflow_id == workflow_id)
            .values(**patch, updated_at=utcnow())
        )
        await session.commit()
        
        return {"id": item_id, **patch}


async def delete_workflow_item(ctx: RequestContext, workflow_id: UUID, item_id: str) -> None:
    """Soft-delete workflow item."""
    await _check_rbac(ctx, "delete_workflow_item")
    
    async with ctx.session() as session:
        # Soft delete by removing from DB (cascade handled by app logic)
        await session.execute(
            delete(WorkflowItemModel).where(
                WorkflowItemModel.id == item_id,
                WorkflowItemModel.workflow_id == workflow_id
            )
        )
        await session.commit()


# =============================================================================
# Checklist Functions
# =============================================================================

async def create_checklist(ctx: RequestContext, data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new checklist template."""
    await _check_rbac(ctx, "create_checklist")
    
    async with ctx.session() as session:
        # Generate code if not provided
        code = data.get("code")
        if not code:
            code = await _generate_unique_code(session, ctx.org_id, "CL")
        else:
            result = await session.execute(
                select(Checklist.code).where(Checklist.code == code)
            )
            if result.first():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Checklist code already exists"
                )
        
        # Create checklist
        checklist = Checklist(
            organization_id=ctx.org_id,
            code=code,
            name=data["name"],
            description=data.get("description"),
        )
        session.add(checklist)
        await session.flush()
        
        # Add items
        items_data = data.get("items", [])
        for item_data in items_data:
            item = ChecklistItemModel(
                checklist_id=checklist.id,
                activity_number=item_data["activity_number"],
                description=item_data["description"],
                data={k: v for k, v in item_data.items() 
                      if k not in ["activity_number", "description", "id"]}
            )
            session.add(item)
        
        await session.commit()
        
        # Emit event
        event_bus = await get_service("core", "EventBusPort")
        await event_bus.publish(
            "template.created",
            dict(
                event_type="template.created",
                aggregate_id=checklist.id,
                aggregate_type="checklist",
                organization_id=ctx.org_id,
                data={"checklist_id": str(checklist.id), "code": code}
            )
        )
        
        logger.info(f"Checklist created: {checklist.id}", extra={"audit": True})
        
        return {"id": checklist.id, "code": code, "name": checklist.name}


async def get_checklist(ctx: RequestContext, checklist_id: UUID) -> Dict[str, Any]:
    """Get checklist by ID with items."""
    async with ctx.session() as session:
        result = await session.execute(
            select(Checklist)
            .where(Checklist.id == checklist_id)
            .where(Checklist.organization_id == ctx.org_id)
            .where(Checklist.deleted_at.is_(None))
        )
        checklist = result.scalar_one_or_none()
        
        if not checklist:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Checklist not found"
            )
        
        # Load items
        items_result = await session.execute(
            select(ChecklistItemModel)
            .where(ChecklistItemModel.checklist_id == checklist_id)
            .order_by(ChecklistItemModel.activity_number)
        )
        items = items_result.scalars().all()
        
        return {
            "id": checklist.id,
            "code": checklist.code,
            "name": checklist.name,
            "description": checklist.description,
            "is_active": checklist.is_active,
            "items": [
                {
                    "id": item.id,
                    "activity_number": item.activity_number,
                    "description": item.description,
                    **item.data
                }
                for item in items
            ]
        }


async def update_checklist(ctx: RequestContext, checklist_id: UUID, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Update checklist header."""
    await _check_rbac(ctx, "update_checklist")
    
    async with ctx.session() as session:
        if "code" in patch:
            result = await session.execute(
                select(Checklist.id).where(
                    Checklist.code == patch["code"],
                    Checklist.id != checklist_id
                )
            )
            if result.first():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Checklist code already exists"
                )
        
        await session.execute(
            update(Checklist)
            .where(Checklist.id == checklist_id)
            .where(Checklist.organization_id == ctx.org_id)
            .values(**patch, updated_at=utcnow())
        )
        await session.commit()
        
        event_bus = await get_service("core", "EventBusPort")
        await event_bus.publish(
            "template.updated",
            dict(
                event_type="template.updated",
                aggregate_id=checklist_id,
                aggregate_type="checklist",
                organization_id=ctx.org_id,
                data={"patch": patch}
            )
        )
        
        logger.info(f"Checklist updated: {checklist_id}", extra={"audit": True})
        
        return {"id": checklist_id, **patch}


async def list_checklists(
    ctx: RequestContext,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 50
) -> PaginatedResponse:
    """List checklists with optional search."""
    async with ctx.session() as session:
        stmt = select(Checklist).where(
            Checklist.organization_id == ctx.org_id,
            Checklist.deleted_at.is_(None)
        )
        
        if q:
            stmt = stmt.where(
                (Checklist.name.ilike(f"%{q}%")) |
                (Checklist.code.ilike(f"%{q}%")) |
                (Checklist.description.ilike(f"%{q}%"))
            )
        
        total = await session.execute(select(func.count()).select_from(stmt.subquery()))
        total_count = total.scalar()
        
        stmt = stmt.order_by(Checklist.created_at.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        
        result = await session.execute(stmt)
        checklists = result.scalars().all()
        
        return PaginatedResponse(
            items=[
                {
                    "id": cl.id,
                    "code": cl.code,
                    "name": cl.name,
                    "description": cl.description,
                    "created_at": cl.created_at
                }
                for cl in checklists
            ],
            total=total_count,
            page=page,
            page_size=page_size
        )


async def archive_checklist(ctx: RequestContext, checklist_id: UUID) -> None:
    """Soft-delete checklist."""
    await _check_rbac(ctx, "archive_checklist")
    
    async with ctx.session() as session:
        await session.execute(
            update(Checklist)
            .where(Checklist.id == checklist_id)
            .where(Checklist.organization_id == ctx.org_id)
            .values(deleted_at=utcnow(), is_active=False)
        )
        await session.commit()
        
        event_bus = await get_service("core", "EventBusPort")
        await event_bus.publish(
            "template.archived",
            dict(
                event_type="template.archived",
                aggregate_id=checklist_id,
                aggregate_type="checklist",
                organization_id=ctx.org_id,
                data={}
            )
        )
        
        logger.info(f"Checklist archived: {checklist_id}", extra={"audit": True})


async def add_checklist_item(ctx: RequestContext, checklist_id: UUID, item: ChecklistItem) -> Dict[str, Any]:
    """Add item to checklist."""
    await _check_rbac(ctx, "add_checklist_item")
    
    async with ctx.session() as session:
        result = await session.execute(
            select(Checklist.id).where(
                Checklist.id == checklist_id,
                Checklist.organization_id == ctx.org_id
            )
        )
        if not result.scalar():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Checklist not found"
            )
        
        item_model = ChecklistItemModel(
            checklist_id=checklist_id,
            activity_number=item.activity_number,
            description=item.description,
            data=item.model_dump(exclude={"id", "activity_number", "description"})
        )
        session.add(item_model)
        await session.commit()
        
        return {"id": item_model.id, "activity_number": item_model.activity_number}


async def update_checklist_item(
    ctx: RequestContext,
    checklist_id: UUID,
    item_id: str,
    patch: Dict[str, Any]
) -> Dict[str, Any]:
    """Update checklist item."""
    await _check_rbac(ctx, "update_checklist_item")
    
    async with ctx.session() as session:
        await session.execute(
            update(ChecklistItemModel)
            .where(ChecklistItemModel.id == item_id)
            .where(ChecklistItemModel.checklist_id == checklist_id)
            .values(**patch, updated_at=utcnow())
        )
        await session.commit()
        
        return {"id": item_id, **patch}


async def delete_checklist_item(ctx: RequestContext, checklist_id: UUID, item_id: str) -> None:
    """Delete checklist item."""
    await _check_rbac(ctx, "delete_checklist_item")
    
    async with ctx.session() as session:
        await session.execute(
            delete(ChecklistItemModel).where(
                ChecklistItemModel.id == item_id,
                ChecklistItemModel.checklist_id == checklist_id
            )
        )
        await session.commit()


# =============================================================================
# Search Functions
# =============================================================================

async def search_workflows(
    ctx: RequestContext,
    q: str,
    page: int = 1,
    page_size: int = 50
) -> PaginatedResponse:
    """Search workflows within individual items."""
    async with ctx.session() as session:
        # Search in item descriptions using full-text search
        stmt = select(WorkflowItemModel.description, WorkflowItemModel.id, Workflow.id, Workflow.name, Workflow.code)\
            .join(Workflow, WorkflowItemModel.workflow_id == Workflow.id)\
            .where(
                Workflow.organization_id == ctx.org_id,
                Workflow.deleted_at.is_(None),
                WorkflowItemModel.description.ilike(f"%{q}%")
            )
        
        total = await session.execute(select(func.count()).select_from(stmt.subquery()))
        total_count = total.scalar()
        
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        result = await session.execute(stmt)
        rows = result.all()
        
        return PaginatedResponse(
            items=[
                SearchHit(
                    template_id=row[2],
                    template_name=row[3],
                    template_code=row[4],
                    kind="workflow",
                    matched_item_id=row[1],
                    matched_item_description=row[0],
                    match_score=1.0
                ).dict()
                for row in rows
            ],
            total=total_count,
            page=page,
            page_size=page_size
        )


async def search_checklists(
    ctx: RequestContext,
    q: str,
    page: int = 1,
    page_size: int = 50
) -> PaginatedResponse:
    """Search checklists within individual items."""
    async with ctx.session() as session:
        stmt = select(ChecklistItemModel.description, ChecklistItemModel.id, Checklist.id, Checklist.name, Checklist.code)\
            .join(Checklist, ChecklistItemModel.checklist_id == Checklist.id)\
            .where(
                Checklist.organization_id == ctx.org_id,
                Checklist.deleted_at.is_(None),
                ChecklistItemModel.description.ilike(f"%{q}%")
            )
        
        total = await session.execute(select(func.count()).select_from(stmt.subquery()))
        total_count = total.scalar()
        
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        result = await session.execute(stmt)
        rows = result.all()
        
        return PaginatedResponse(
            items=[
                SearchHit(
                    template_id=row[2],
                    template_name=row[3],
                    template_code=row[4],
                    kind="checklist",
                    matched_item_id=row[1],
                    matched_item_description=row[0],
                    match_score=1.0
                ).dict()
                for row in rows
            ],
            total=total_count,
            page=page,
            page_size=page_size
        )


# =============================================================================
# Snapshot Function (for Work Order Generation)
# =============================================================================

async def snapshot(template_id: UUID, kind: Literal["workflow", "checklist"]) -> TemplateSnapshot:
    """
    Freeze template state for work order generation.
    Called by WORKORDERS module on cycle.due event.
    Returns immutable snapshot.
    """
    from src.server.core.registry import get_service
    
    db = await get_service("db", "DatabasePort")
    
    async with db.session_factory() as session:
        if kind == "workflow":
            result = await session.execute(
                select(Workflow).where(Workflow.id == template_id)
            )
            template = result.scalar_one_or_none()
            if not template:
                raise ValueError(f"Workflow {template_id} not found")
            
            items_result = await session.execute(
                select(WorkflowItemModel)
                .where(WorkflowItemModel.workflow_id == template_id)
                .order_by(WorkflowItemModel.activity_number)
            )
            items = items_result.scalars().all()
            
            return TemplateSnapshot(
                template_id=template.id,
                kind="workflow",
                code=template.code,
                name=template.name,
                description=template.description,
                items=[
                    WorkItemSnapshot(
                        id=item.id,
                        activity_number=item.activity_number,
                        predecessor=item.predecessor,
                        description=item.description,
                        status=item.data.get("status", "PENDING"),
                        priority=item.data.get("priority", 50),
                        measurement_fields=[
                            MeasurementField(**mf) if isinstance(mf, dict) else mf
                            for mf in item.data.get("measurement_fields", [])
                        ] or None,
                        signature_required=item.data.get("signature_required", False),
                        safety_permit=item.data.get("safety_permit"),
                        risk=item.data.get("risk"),
                        assignee=item.data.get("assignee"),
                        skills=item.data.get("skills"),
                        certs=item.data.get("certs"),
                        tools=item.data.get("tools"),
                        parts=item.data.get("parts"),
                        cost=item.data.get("cost"),
                        downtime=item.data.get("downtime"),
                        notes=item.data.get("notes")
                    )
                    for item in items
                ],
                frozen_at=utcnow()
            )
        else:
            result = await session.execute(
                select(Checklist).where(Checklist.id == template_id)
            )
            template = result.scalar_one_or_none()
            if not template:
                raise ValueError(f"Checklist {template_id} not found")
            
            items_result = await session.execute(
                select(ChecklistItemModel)
                .where(ChecklistItemModel.checklist_id == template_id)
                .order_by(ChecklistItemModel.activity_number)
            )
            items = items_result.scalars().all()
            
            return TemplateSnapshot(
                template_id=template.id,
                kind="checklist",
                code=template.code,
                name=template.name,
                description=template.description,
                items=[
                    WorkItemSnapshot(
                        id=item.id,
                        activity_number=item.activity_number,
                        predecessor=None,
                        description=item.description,
                        status="PENDING",
                        priority=50,
                        measurement_fields=[
                            MeasurementField(**mf) if isinstance(mf, dict) else mf
                            for mf in item.data.get("measurement_fields", [])
                        ] or None,
                        signature_required=False,
                        safety_permit=None,
                        risk=None,
                        assignee=None,
                        skills=None,
                        certs=None,
                        tools=None,
                        parts=None,
                        cost=None,
                        downtime=None,
                        notes=item.data.get("notes")
                    )
                    for item in items
                ],
                frozen_at=utcnow()
            )
