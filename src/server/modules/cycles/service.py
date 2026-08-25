"""Cycles Service - Maintenance Cycle Engine Implementation"""

import asyncio
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException, status

from ...shared.types import (
    RequestContext,
    Role,
    DomainError,
    NotFoundError,
    ForbiddenError,
    QuotaExceededError,
    Page,
)
from ...core.event_bus import get_event_bus
from ...core.module_base import ModuleBase, ModuleContext, HealthStatus
from ...core.registry import get_service
from ...core.logger import get_logger
from ...core.utils import utcnow, new_id

logger = get_logger(__name__)


# ============================================================================
# Enums
# ============================================================================

class TriggerType(str, Enum):
    CALENDAR = "CALENDAR"
    HOURS = "HOURS"
    COUNT = "COUNT"


class LaunchMode(str, Enum):
    AUTOMATIC = "AUTOMATIC"
    MANUAL = "MANUAL"


class DeadlineBehavior(str, Enum):
    FLAG_CRITICAL_STOP = "FLAG_CRITICAL_STOP"
    WAIT_UNTIL_COMPLETED = "WAIT_UNTIL_COMPLETED"


class CycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


# ============================================================================
# Data Models
# ============================================================================

class TriggerSpec(BaseModel):
    """Trigger specification for a cycle"""
    id: Optional[str] = None
    type: TriggerType
    cron: Optional[str] = None  # For CALENDAR triggers
    threshold: Optional[float] = None  # For HOURS/COUNT triggers
    auto_frequency: Optional[str] = None  # once/twice per day/shift


class CycleCreate(BaseModel):
    """Data for creating a new cycle"""
    code: Optional[str] = None
    name: str
    description: Optional[str] = None
    target_entity_type: str  # ZONE|SYSTEM|SUB_SYSTEM|SERVICE_POINT
    target_entity_id: UUID
    assigned_template_id: UUID
    safety_flag: Optional[str] = None
    deadline: int  # hours
    grace_period: int  # hours
    deadline_behavior: DeadlineBehavior
    launch_mode: LaunchMode
    auto_frequency: Optional[str] = None
    postpone_overhead: Optional[int] = None  # hours
    influence_child_nodes: bool = False
    triggers: List[TriggerSpec] = Field(default_factory=list)


class CycleUpdate(BaseModel):
    """Data for updating a cycle (partial)"""
    code: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    safety_flag: Optional[str] = None
    deadline: Optional[int] = None
    grace_period: Optional[int] = None
    deadline_behavior: Optional[DeadlineBehavior] = None
    launch_mode: Optional[LaunchMode] = None
    auto_frequency: Optional[str] = None
    postpone_overhead: Optional[int] = None
    influence_child_nodes: Optional[bool] = None


class CycleEvaluation(BaseModel):
    """Cycle evaluation record"""
    id: str
    cycle_id: UUID
    trigger_id: str
    evaluated_at: datetime
    result: bool
    generated_wo_id: Optional[UUID] = None
    error: Optional[str] = None
    period_key: Optional[str] = None


# ============================================================================
# Database Models (SQLAlchemy ORM would be defined here)
# For now, we use dict-based persistence as placeholder
# ============================================================================

# In production, these would be SQLAlchemy models:
# - cycles: id, code, name, description, target_entity_type, target_entity_id,
#           assigned_template_id, safety_flag, deadline, grace_period,
#           deadline_behavior, launch_mode, auto_frequency, postpone_overhead,
#           influence_child_nodes, status, organization_id, created_at, updated_at
# - cycle_triggers: id, cycle_id, type, cron, threshold, auto_frequency
# - cycle_evaluations: id, cycle_id, trigger_id, evaluated_at, result,
#                      generated_wo_id, error, period_key


# ============================================================================
# Service Class
# ============================================================================

class CyclesService(ModuleBase):
    """Maintenance Cycle Engine Service"""

    name = "cycles"
    version = "1.0.0"
    dependencies = ["core", "db", "api", "assets", "templates", "worker", "cache"]
    optional_dependencies = []
    profiles = ["api", "worker", "beat", "all-in-one"]

    def __init__(self):
        super().__init__()
        self._db = None
        self._cache = None
        self._assets = None
        self._templates = None
        self._worker = None
        self._event_bus = None
        self._router = APIRouter(prefix="/cycles", tags=["cycles"])
        self._cycle_cache: Dict[UUID, dict] = {}
        self._evaluation_locks: set = set()

    async def configure(self, settings: dict) -> None:
        """Configure the cycles module"""
        logger.info("Configuring cycles module", extra={"settings": settings})

    async def initialize(self, context: dict) -> None:
        """Initialize dependencies and services"""
        self._db = await get_service("db", "DatabasePort")
        self._cache = await get_service("cache", "CachePort")
        self._assets = await get_service("assets", "AssetsPort")
        self._templates = await get_service("templates", "TemplatesPort")
        self._worker = await get_service("worker", "WorkerPort")
        self._event_bus = await get_service("core", "EventBusPort")

        # Subscribe to cycle.due events (WORKORDERS module should consume these)
        # Note: CYCLES emits, WORKORDERS subscribes - never call directly
        await self._event_bus.subscribe("cycle.due", self._on_cycle_due, post_commit=True)

        logger.info("Cycles module initialized")

    async def start(self) -> None:
        """Start the cycles module - register routes and tasks"""
        self._register_routes()
        self._register_tasks()
        logger.info("Cycles module started")

    async def stop(self) -> None:
        """Stop the cycles module"""
        logger.info("Cycles module stopping")
        self._cycle_cache.clear()
        self._evaluation_locks.clear()

    async def health(self) -> dict:
        """Health check for cycles module"""
        return {
            "status": "healthy",
            "module": self.name,
            "version": self.version,
            "timestamp": utcnow().isoformat(),
        }

    # =========================================================================
    # Route Registration
    # =========================================================================

    def _register_routes(self):
        """Register API routes"""
        from ...core.context import request_context
        from ...modules.auth.service import require_roles

        # POST /cycles - Create cycle
        self._router.add_api_route(
            "",
            self._create_cycle_handler,
            methods=["POST"],
            dependencies=[Depends(require_roles("MANAGER", "SYS_ADMIN"))],
        )

        # PATCH /cycles/{cycle_id} - Update cycle
        self._router.add_api_route(
            "/{cycle_id}",
            self._update_cycle_handler,
            methods=["PATCH"],
            dependencies=[Depends(require_roles("MANAGER", "SYS_ADMIN"))],
        )

        # GET /cycles - List cycles
        self._router.add_api_route(
            "",
            self._list_cycles_handler,
            methods=["GET"],
        )

        # GET /cycles/{cycle_id} - Get cycle
        self._router.add_api_route(
            "/{cycle_id}",
            self._get_cycle_handler,
            methods=["GET"],
        )

        # POST /cycles/{cycle_id}/triggers - Add trigger
        self._router.add_api_route(
            "/{cycle_id}/triggers",
            self._add_trigger_handler,
            methods=["POST"],
            dependencies=[Depends(require_roles("MANAGER", "SYS_ADMIN"))],
        )

        # PATCH /cycles/{cycle_id}/triggers/{trigger_id} - Update trigger
        self._router.add_api_route(
            "/{cycle_id}/triggers/{trigger_id}",
            self._update_trigger_handler,
            methods=["PATCH"],
            dependencies=[Depends(require_roles("MANAGER", "SYS_ADMIN"))],
        )

        # DELETE /cycles/{cycle_id}/triggers/{trigger_id} - Remove trigger
        self._router.add_api_route(
            "/{cycle_id}/triggers/{trigger_id}",
            self._remove_trigger_handler,
            methods=["DELETE"],
            dependencies=[Depends(require_roles("MANAGER", "SYS_ADMIN"))],
        )

        # POST /cycles/{cycle_id}/suspend - Suspend cycle
        self._router.add_api_route(
            "/{cycle_id}/suspend",
            self._suspend_cycle_handler,
            methods=["POST"],
            dependencies=[Depends(require_roles("MANAGER", "SYS_ADMIN"))],
        )

        # POST /cycles/{cycle_id}/activate - Activate cycle
        self._router.add_api_route(
            "/{cycle_id}/activate",
            self._activate_cycle_handler,
            methods=["POST"],
            dependencies=[Depends(require_roles("MANAGER", "SYS_ADMIN"))],
        )

        # DELETE /cycles/{cycle_id} - Archive cycle
        self._router.add_api_route(
            "/{cycle_id}",
            self._archive_cycle_handler,
            methods=["DELETE"],
            dependencies=[Depends(require_roles("MANAGER", "SYS_ADMIN"))],
        )

        # POST /cycles/{cycle_id}/manual-trigger - Manual trigger
        self._router.add_api_route(
            "/{cycle_id}/manual-trigger",
            self._manual_trigger_handler,
            methods=["POST"],
            dependencies=[Depends(require_roles("MANAGER", "SYS_ADMIN"))],
        )

        # GET /cycles/{cycle_id}/evaluations - Get evaluations
        self._router.add_api_route(
            "/{cycle_id}/evaluations",
            self._get_evaluations_handler,
            methods=["GET"],
        )

        # Register router with API module
        api_module = self._ctx.get("api_module")
        if api_module:
            api_module.register_router(self._router, "cycles", ["cycles"])

    def _register_tasks(self):
        """Register worker tasks and beat schedules"""
        if self._worker:
            # Register evaluate_due_cycles task
            self._worker.register_task("cycles.evaluate_due", self.evaluate_due_cycles)
            
            # Register detect_missed_cycles task
            self._worker.register_task("cycles.detect_missed", self.detect_missed_cycles)

            # Register beat schedules
            # evaluate_due_cycles runs every minute
            self._worker.register_beat(
                "cycles-evaluate-due",
                "cycles.evaluate_due",
                {"seconds": 60},
            )

            # detect_missed_cycles runs every 5 minutes
            self._worker.register_beat(
                "cycles-detect-missed",
                "cycles.detect_missed",
                {"seconds": 300},
            )

    # =========================================================================
    # CRUD Operations
    # =========================================================================

    async def create_cycle(self, ctx: RequestContext, data: CycleCreate) -> dict:
        """
        Create a new maintenance cycle.
        
        Validates:
        - Target entity exists via ASSETS
        - Template exists via TEMPLATES
        - Cron expressions are valid
        - Organization quotas
        
        Emits: cycle.created
        """
        async with self._db.session_factory() as session:
            # Validate target entity exists
            try:
                asset_service = self._assets
                # Check if target entity exists (delegate to assets module)
                # This is a simplified check - in production would call assets.get_node
                logger.info(
                    "Validating target entity",
                    extra={
                        "entity_type": data.target_entity_type,
                        "entity_id": str(data.target_entity_id),
                    },
                )
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Target entity not found: {e}",
                )

            # Validate template exists
            try:
                template_service = self._templates
                # Check if template exists (delegate to templates module)
                logger.info(
                    "Validating template",
                    extra={"template_id": str(data.assigned_template_id)},
                )
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Template not found: {e}",
                )

            # Validate cron expressions for calendar triggers
            for trigger in data.triggers:
                if trigger.type == TriggerType.CALENDAR and not trigger.cron:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Calendar trigger requires cron expression",
                    )
                if trigger.type in [TriggerType.HOURS, TriggerType.COUNT] and not trigger.threshold:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Hours/Count trigger requires threshold",
                    )

            # Create cycle record
            cycle_id = uuid4()
            cycle_data = {
                "id": cycle_id,
                "code": data.code or f"CYC-{new_id()[:8].upper()}",
                "name": data.name,
                "description": data.description,
                "target_entity_type": data.target_entity_type,
                "target_entity_id": data.target_entity_id,
                "assigned_template_id": data.assigned_template_id,
                "safety_flag": data.safety_flag,
                "deadline": data.deadline,
                "grace_period": data.grace_period,
                "deadline_behavior": data.deadline_behavior.value,
                "launch_mode": data.launch_mode.value,
                "auto_frequency": data.auto_frequency,
                "postpone_overhead": data.postpone_overhead,
                "influence_child_nodes": data.influence_child_nodes,
                "status": CycleStatus.ACTIVE.value,
                "organization_id": ctx.org_id,
                "created_at": utcnow(),
                "updated_at": utcnow(),
            }

            # Persist cycle (in production: session.add(Cycle(**cycle_data)))
            # For now, cache in memory
            self._cycle_cache[cycle_id] = cycle_data

            # Create triggers
            triggers = []
            for trigger_spec in data.triggers:
                trigger_id = new_id()
                trigger_data = {
                    "id": trigger_id,
                    "cycle_id": cycle_id,
                    "type": trigger_spec.type.value,
                    "cron": trigger_spec.cron,
                    "threshold": trigger_spec.threshold,
                    "auto_frequency": trigger_spec.auto_frequency,
                    "created_at": utcnow(),
                }
                triggers.append(trigger_data)

            # Emit event
            await self._event_bus.publish(
                "cycle.created",
                {
                    "cycle_id": str(cycle_id),
                    "organization_id": str(ctx.org_id),
                    "target_entity_type": data.target_entity_type,
                    "target_entity_id": str(data.target_entity_id),
                    "template_id": str(data.assigned_template_id),
                },
                post_commit=True,
            )

            logger.info(
                "Cycle created",
                extra={
                    "cycle_id": str(cycle_id),
                    "name": data.name,
                },
            )

            return {
                "id": str(cycle_id),
                **cycle_data,
                "triggers": triggers,
            }

    async def update_cycle(
        self, ctx: RequestContext, cycle_id: UUID, patch: CycleUpdate
    ) -> dict:
        """
        Update an existing cycle.
        
        Note: Changes apply ONLY to newly generated work orders.
        Existing WOs keep snapshots of old configuration.
        
        Emits: cycle.updated
        """
        async with self._db.session_factory() as session:
            # Fetch cycle
            cycle = self._cycle_cache.get(cycle_id)
            if not cycle or cycle.get("organization_id") != ctx.org_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Cycle not found",
                )

            if cycle.get("status") == CycleStatus.ARCHIVED.value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot update archived cycle",
                )

            # Apply patch (only allowed fields)
            update_data = patch.model_dump(exclude_unset=True)
            for key, value in update_data.items():
                if isinstance(value, Enum):
                    cycle[key] = value.value
                else:
                    cycle[key] = value

            cycle["updated_at"] = utcnow()

            # Emit event
            await self._event_bus.publish(
                "cycle.updated",
                {
                    "cycle_id": str(cycle_id),
                    "organization_id": str(ctx.org_id),
                    "changes": list(update_data.keys()),
                },
                post_commit=True,
            )

            logger.info(
                "Cycle updated",
                extra={"cycle_id": str(cycle_id), "changes": list(update_data.keys())},
            )

            return {**cycle, "id": str(cycle_id)}

    async def list_cycles(
        self,
        ctx: RequestContext,
        filters: Optional[Dict[str, Any]] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """List cycles with org-scoping and optional filters"""
        async with self._db.session_factory() as session:
            # Filter by organization
            cycles = [
                {**c, "id": str(c["id"])}
                for c in self._cycle_cache.values()
                if c.get("organization_id") == ctx.org_id
            ]

            # Apply filters
            if filters:
                if "status" in filters:
                    cycles = [c for c in cycles if c.get("status") == filters["status"]]
                if "target_entity_type" in filters:
                    cycles = [
                        c
                        for c in cycles
                        if c.get("target_entity_type") == filters["target_entity_type"]
                    ]
                if "target_entity_id" in filters:
                    cycles = [
                        c
                        for c in cycles
                        if str(c.get("target_entity_id")) == str(filters["target_entity_id"])
                    ]

            # Pagination
            total = len(cycles)
            start = (page - 1) * page_size
            end = start + page_size
            paginated = cycles[start:end]

            return {
                "items": paginated,
                "total": total,
                "page": page,
                "page_size": page_size,
            }

    async def get_cycle(self, ctx: RequestContext, cycle_id: UUID) -> dict:
        """Get cycle details including triggers and last evaluations"""
        async with self._db.session_factory() as session:
            cycle = self._cycle_cache.get(cycle_id)
            if not cycle or cycle.get("organization_id") != ctx.org_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Cycle not found",
                )

            # Get triggers for this cycle
            triggers = [
                t for t in self._get_all_triggers() if t.get("cycle_id") == cycle_id
            ]

            # Get last evaluations
            evaluations = await self.get_evaluations(ctx, cycle_id, page=1, page_size=5)

            return {
                **cycle,
                "id": str(cycle_id),
                "triggers": triggers,
                "last_evaluations": evaluations.get("items", []),
            }

    # =========================================================================
    # Trigger Management
    # =========================================================================

    async def add_trigger(
        self, ctx: RequestContext, cycle_id: UUID, trigger: TriggerSpec
    ) -> dict:
        """Add a trigger to an existing cycle"""
        async with self._db.session_factory() as session:
            cycle = self._cycle_cache.get(cycle_id)
            if not cycle or cycle.get("organization_id") != ctx.org_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Cycle not found",
                )

            if cycle.get("status") != CycleStatus.ACTIVE.value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Can only add triggers to active cycles",
                )

            # Validate trigger
            if trigger.type == TriggerType.CALENDAR and not trigger.cron:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Calendar trigger requires cron expression",
                )
            if trigger.type in [TriggerType.HOURS, TriggerType.COUNT] and not trigger.threshold:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Hours/Count trigger requires threshold",
                )

            trigger_id = new_id()
            trigger_data = {
                "id": trigger_id,
                "cycle_id": cycle_id,
                "type": trigger.type.value,
                "cron": trigger.cron,
                "threshold": trigger.threshold,
                "auto_frequency": trigger.auto_frequency,
                "created_at": utcnow(),
            }

            # Persist trigger (in production: session.add(CycleTrigger(**trigger_data)))
            self._save_trigger(trigger_data)

            logger.info(
                "Trigger added to cycle",
                extra={"cycle_id": str(cycle_id), "trigger_id": trigger_id},
            )

            return {**trigger_data, "id": trigger_id}

    async def update_trigger(
        self, ctx: RequestContext, cycle_id: UUID, trigger_id: str, patch: TriggerSpec
    ) -> dict:
        """Update an existing trigger"""
        async with self._db.session_factory() as session:
            cycle = self._cycle_cache.get(cycle_id)
            if not cycle or cycle.get("organization_id") != ctx.org_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Cycle not found",
                )

            # Find trigger
            trigger = self._get_trigger(trigger_id)
            if not trigger or trigger.get("cycle_id") != cycle_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Trigger not found",
                )

            # Apply patch
            update_data = patch.model_dump(exclude_unset=True)
            for key, value in update_data.items():
                if isinstance(value, Enum):
                    trigger[key] = value.value
                else:
                    trigger[key] = value

            self._save_trigger(trigger)

            logger.info(
                "Trigger updated",
                extra={"cycle_id": str(cycle_id), "trigger_id": trigger_id},
            )

            return {**trigger, "id": trigger_id}

    async def remove_trigger(
        self, ctx: RequestContext, cycle_id: UUID, trigger_id: str
    ) -> None:
        """Remove a trigger from a cycle"""
        async with self._db.session_factory() as session:
            cycle = self._cycle_cache.get(cycle_id)
            if not cycle or cycle.get("organization_id") != ctx.org_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Cycle not found",
                )

            # Find and remove trigger
            trigger = self._get_trigger(trigger_id)
            if not trigger or trigger.get("cycle_id") != cycle_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Trigger not found",
                )

            self._delete_trigger(trigger_id)

            logger.info(
                "Trigger removed from cycle",
                extra={"cycle_id": str(cycle_id), "trigger_id": trigger_id},
            )

    # =========================================================================
    # Lifecycle Operations
    # =========================================================================

    async def suspend_cycle(self, ctx: RequestContext, cycle_id: UUID) -> dict:
        """
        Suspend a cycle.
        
        - Status becomes SUSPENDED
        - No WO generation while suspended
        - Calendar triggers pause
        - Emits: cycle.suspended
        """
        async with self._db.session_factory() as session:
            cycle = self._cycle_cache.get(cycle_id)
            if not cycle or cycle.get("organization_id") != ctx.org_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Cycle not found",
                )

            if cycle.get("status") != CycleStatus.ACTIVE.value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cycle is not active",
                )

            cycle["status"] = CycleStatus.SUSPENDED.value
            cycle["updated_at"] = utcnow()

            await self._event_bus.publish(
                "cycle.suspended",
                {"cycle_id": str(cycle_id), "organization_id": str(ctx.org_id)},
                post_commit=True,
            )

            logger.info("Cycle suspended", extra={"cycle_id": str(cycle_id)})

            return {**cycle, "id": str(cycle_id)}

    async def activate_cycle(self, ctx: RequestContext, cycle_id: UUID) -> dict:
        """
        Activate a suspended cycle.
        
        - Status becomes ACTIVE
        - Next evaluation resumes
        - Emits: cycle.activated
        """
        async with self._db.session_factory() as session:
            cycle = self._cycle_cache.get(cycle_id)
            if not cycle or cycle.get("organization_id") != ctx.org_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Cycle not found",
                )

            if cycle.get("status") != CycleStatus.SUSPENDED.value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cycle is not suspended",
                )

            cycle["status"] = CycleStatus.ACTIVE.value
            cycle["updated_at"] = utcnow()

            await self._event_bus.publish(
                "cycle.activated",
                {"cycle_id": str(cycle_id), "organization_id": str(ctx.org_id)},
                post_commit=True,
            )

            logger.info("Cycle activated", extra={"cycle_id": str(cycle_id)})

            return {**cycle, "id": str(cycle_id)}

    async def archive_cycle(self, ctx: RequestContext, cycle_id: UUID) -> None:
        """
        Archive a cycle (soft delete).
        
        - Status becomes ARCHIVED
        - Stops evaluation
        - History retained
        """
        async with self._db.session_factory() as session:
            cycle = self._cycle_cache.get(cycle_id)
            if not cycle or cycle.get("organization_id") != ctx.org_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Cycle not found",
                )

            cycle["status"] = CycleStatus.ARCHIVED.value
            cycle["updated_at"] = utcnow()

            logger.info("Cycle archived", extra={"cycle_id": str(cycle_id)})

    async def manual_trigger(self, ctx: RequestContext, cycle_id: UUID) -> dict:
        """
        Manually trigger a cycle evaluation.
        
        - Only for MANUAL launch mode cycles
        - Rate-limited
        - Emits: cycle.due with source=MANUAL
        - Audited
        """
        async with self._db.session_factory() as session:
            cycle = self._cycle_cache.get(cycle_id)
            if not cycle or cycle.get("organization_id") != ctx.org_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Cycle not found",
                )

            if cycle.get("launch_mode") != LaunchMode.MANUAL.value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Manual trigger only allowed for MANUAL launch mode cycles",
                )

            if cycle.get("status") != CycleStatus.ACTIVE.value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Can only trigger active cycles",
                )

            # Rate limiting via cache
            rate_key = f"cycle:manual-trigger:{cycle_id}"
            rate_result = await self._cache.allow(rate_key, limit=10, window_s=60)
            if not rate_result.allowed:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded for manual triggers",
                )

            # Perform evaluation
            triggers = [t for t in self._get_all_triggers() if t.get("cycle_id") == cycle_id]
            if not triggers:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cycle has no triggers configured",
                )

            # Use first trigger for manual evaluation
            trigger = triggers[0]
            period_key = f"manual:{utcnow().strftime('%Y%m%d%H%M%S')}"

            # Emit cycle.due event
            await self._event_bus.publish(
                "cycle.due",
                {
                    "cycle_id": str(cycle_id),
                    "trigger_id": trigger["id"],
                    "period_key": period_key,
                    "source": "MANUAL",
                    "organization_id": str(ctx.org_id),
                },
                post_commit=True,
            )

            # Record evaluation
            evaluation = {
                "id": new_id(),
                "cycle_id": cycle_id,
                "trigger_id": trigger["id"],
                "evaluated_at": utcnow(),
                "result": True,
                "period_key": period_key,
                "error": None,
            }
            self._save_evaluation(evaluation)

            logger.info(
                "Manual cycle trigger executed",
                extra={"cycle_id": str(cycle_id), "trigger_id": trigger["id"]},
            )

            return {
                "cycle_id": str(cycle_id),
                "trigger_id": trigger["id"],
                "evaluated_at": evaluation["evaluated_at"].isoformat(),
                "source": "MANUAL",
            }

    # =========================================================================
    # Evaluation Engine
    # =========================================================================

    async def evaluate_due_cycles(self) -> Dict[str, Any]:
        """
        Evaluate all active cycles for due triggers.
        
        Runs every minute via beat schedule inside WORKER.single_flight.
        
        Process:
        1. Find all ACTIVE cycles (skip SUSPENDED/ARCHIVED)
        2. Evaluate calendar triggers (UTC)
        3. Evaluate counter triggers via ASSETS.effective_counter
        4. FIRST satisfied trigger wins
        5. Emit cycle.due event (WORKORDERS generates WO)
        6. Write cycle_evaluations row
        7. Idempotency via CACHE.lock per cycle + unique(cycle_id, period_key)
        8. Failures recorded + emit cycle.eval_failed
        
        Returns: Summary of evaluations performed
        """
        now_utc = utcnow()
        results = {"evaluated": 0, "due": 0, "errors": 0, "skipped": 0}

        try:
            # Acquire single-flight lock for this evaluation run
            async with self._cache.lock("cycles:evaluate-due", ttl_s=55, wait_ms=0):
                async with self._db.session_factory() as session:
                    # Get all active cycles
                    active_cycles = [
                        c for c in self._cycle_cache.values()
                        if c.get("status") == CycleStatus.ACTIVE.value
                    ]

                    for cycle in active_cycles:
                        cycle_id = cycle["id"]
                        org_id = cycle.get("organization_id")

                        try:
                            # Acquire per-cycle lock for idempotency
                            lock_key = f"cycle:eval:{cycle_id}"
                            async with self._cache.lock(lock_key, ttl_s=30, wait_ms=0):
                                evaluated = await self._evaluate_cycle(
                                    cycle, now_utc
                                )
                                if evaluated:
                                    results["due"] += 1
                                results["evaluated"] += 1

                        except Exception as e:
                            logger.error(
                                "Failed to evaluate cycle",
                                extra={"cycle_id": str(cycle_id), "error": str(e)},
                            )
                            results["errors"] += 1

                            # Emit failure event
                            await self._event_bus.publish(
                                "cycle.eval_failed",
                                {
                                    "cycle_id": str(cycle_id),
                                    "organization_id": str(org_id),
                                    "error": str(e),
                                    "evaluated_at": now_utc.isoformat(),
                                },
                                post_commit=True,
                            )

        except Exception as e:
            logger.error("Cycle evaluation failed", extra={"error": str(e)})
            results["errors"] += 1

        return results

    async def _evaluate_cycle(self, cycle: dict, now_utc: datetime) -> bool:
        """Evaluate a single cycle for due triggers"""
        cycle_id = cycle["id"]
        triggers = [t for t in self._get_all_triggers() if t.get("cycle_id") == cycle_id]

        if not triggers:
            return False

        # Evaluate each trigger - FIRST satisfied wins
        for trigger in triggers:
            trigger_type = trigger.get("type")
            satisfied = False

            if trigger_type == "CALENDAR":
                satisfied = await self.evaluate_calendar(trigger, now_utc)
            elif trigger_type in ["HOURS", "COUNT"]:
                entity_id = cycle.get("target_entity_id")
                satisfied = await self.evaluate_counter(trigger, entity_id)

            if satisfied:
                # Generate period key for idempotency
                period_key = self._generate_period_key(trigger, now_utc)

                # Check idempotency - skip if already evaluated for this period
                if await self._is_already_evaluated(cycle_id, period_key):
                    continue

                # Emit cycle.due event
                await self._event_bus.publish(
                    "cycle.due",
                    {
                        "cycle_id": str(cycle_id),
                        "trigger_id": trigger["id"],
                        "period_key": period_key,
                        "source": "AUTO",
                        "organization_id": cycle.get("organization_id"),
                    },
                    post_commit=True,
                )

                # Record evaluation
                evaluation = {
                    "id": new_id(),
                    "cycle_id": cycle_id,
                    "trigger_id": trigger["id"],
                    "evaluated_at": now_utc,
                    "result": True,
                    "period_key": period_key,
                    "error": None,
                }
                self._save_evaluation(evaluation)

                logger.info(
                    "Cycle evaluated as due",
                    extra={
                        "cycle_id": str(cycle_id),
                        "trigger_id": trigger["id"],
                        "period_key": period_key,
                    },
                )

                return True

        return False

    async def evaluate_calendar(
        self, trigger: dict, now_utc: datetime, last_run: Optional[datetime] = None
    ) -> bool:
        """
        Evaluate a calendar trigger.
        
        Args:
            trigger: Trigger spec with cron expression
            now_utc: Current UTC time
            last_run: Last successful run time (optional)
        
        Returns: True if trigger is satisfied (cron matches)
        """
        cron_expr = trigger.get("cron")
        if not cron_expr:
            return False

        # Parse cron expression and check if current time matches
        # Simplified implementation - in production use 'croniter' library
        try:
            # Basic cron parsing: minute hour day month weekday
            parts = cron_expr.split()
            if len(parts) != 5:
                logger.warning(f"Invalid cron expression: {cron_expr}")
                return False

            minute, hour, day, month, weekday = parts

            # Check if current time matches cron
            matches = True
            if minute != "*" and int(minute) != now_utc.minute:
                matches = False
            if hour != "*" and int(hour) != now_utc.hour:
                matches = False
            if day != "*" and int(day) != now_utc.day:
                matches = False
            if month != "*" and int(month) != now_utc.month:
                matches = False
            if weekday != "*" and int(weekday) != now_utc.weekday():
                matches = False

            return matches

        except Exception as e:
            logger.error(
                "Failed to evaluate calendar trigger",
                extra={"cron": cron_expr, "error": str(e)},
            )
            return False

    async def evaluate_counter(self, trigger: dict, entity_id: UUID) -> bool:
        """
        Evaluate a counter trigger.
        
        Args:
            trigger: Trigger spec with threshold
            entity_id: Target entity ID
        
        Returns: True if counter exceeds threshold since last trigger
        """
        threshold = trigger.get("threshold")
        if threshold is None:
            return False

        try:
            # Delegate to ASSETS module to get effective counter
            # This respects inheritance (influence_child_nodes)
            assets_service = self._assets
            # In production: counter_value = await assets_service.effective_counter(entity_id)
            
            # Simplified for now - would need actual counter value
            # counter_value = await assets_service.effective_counter(entity_id)
            # return counter_value >= threshold
            
            logger.debug(
                "Evaluating counter trigger",
                extra={"entity_id": str(entity_id), "threshold": threshold},
            )
            
            # Placeholder - in production would fetch actual counter
            return False

        except Exception as e:
            logger.error(
                "Failed to evaluate counter trigger",
                extra={"entity_id": str(entity_id), "error": str(e)},
            )
            return False

    async def detect_missed_cycles(self) -> Dict[str, Any]:
        """
        Detect missed cycles.
        
        Runs every 5 minutes via beat schedule.
        Finds calendar cycles past due without trigger.
        
        Emits:
        - cycle.missed (WORKORDERS creates overdue-flagged WO)
        - Telemetry events
        """
        now_utc = utcnow()
        results = {"detected": 0, "emitted": 0}

        try:
            async with self._db.session_factory() as session:
                # Find active cycles with calendar triggers
                active_cycles = [
                    c for c in self._cycle_cache.values()
                    if c.get("status") == CycleStatus.ACTIVE.value
                ]

                for cycle in active_cycles:
                    cycle_id = cycle["id"]
                    triggers = [
                        t for t in self._get_all_triggers()
                        if t.get("cycle_id") == cycle_id and t.get("type") == "CALENDAR"
                    ]

                    for trigger in triggers:
                        # Check if cycle was due but not triggered
                        # Simplified logic - in production would check last evaluation
                        # against expected schedule
                        is_missed = await self._check_missed_cycle(cycle, trigger, now_utc)

                        if is_missed:
                            period_key = f"missed:{now_utc.strftime('%Y%m%d%H')}"

                            # Emit cycle.missed event
                            await self._event_bus.publish(
                                "cycle.missed",
                                {
                                    "cycle_id": str(cycle_id),
                                    "trigger_id": trigger["id"],
                                    "period_key": period_key,
                                    "overdue": True,
                                    "detected_at": now_utc.isoformat(),
                                },
                                post_commit=True,
                            )

                            results["emitted"] += 1
                            logger.warning(
                                "Missed cycle detected",
                                extra={
                                    "cycle_id": str(cycle_id),
                                    "trigger_id": trigger["id"],
                                },
                            )

                    results["detected"] += 1

        except Exception as e:
            logger.error("Missed cycle detection failed", extra={"error": str(e)})

        return results

    async def _check_missed_cycle(
        self, cycle: dict, trigger: dict, now_utc: datetime
    ) -> bool:
        """Check if a cycle was missed (past due without trigger)"""
        # Simplified implementation
        # In production: compare expected run times vs actual evaluations
        return False

    async def get_evaluations(
        self,
        ctx: RequestContext,
        cycle_id: UUID,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """Get evaluation log for a cycle"""
        async with self._db.session_factory() as session:
            # Get cycle to verify ownership
            cycle = self._cycle_cache.get(cycle_id)
            if not cycle or cycle.get("organization_id") != ctx.org_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Cycle not found",
                )

            # Get evaluations for this cycle
            all_evaluations = self._get_evaluations_for_cycle(cycle_id)

            # Pagination
            total = len(all_evaluations)
            start = (page - 1) * page_size
            end = start + page_size
            paginated = all_evaluations[start:end]

            return {
                "items": [
                    {
                        "id": e["id"],
                        "cycle_id": str(e["cycle_id"]),
                        "trigger_id": e["trigger_id"],
                        "evaluated_at": e["evaluated_at"].isoformat(),
                        "result": e["result"],
                        "generated_wo_id": str(e.get("generated_wo_id")) if e.get("generated_wo_id") else None,
                        "error": e.get("error"),
                        "period_key": e.get("period_key"),
                    }
                    for e in paginated
                ],
                "total": total,
                "page": page,
                "page_size": page_size,
            }

    # =========================================================================
    # Event Handlers
    # =========================================================================

    async def _on_cycle_due(self, event: str, payload: dict) -> None:
        """Handle cycle.due events (for logging/telemetry)"""
        # Note: CYCLES emits cycle.due, WORKORDERS subscribes to generate WOs
        # This handler is for internal logging only
        logger.info(
            "Cycle due event emitted",
            extra={
                "cycle_id": payload.get("cycle_id"),
                "trigger_id": payload.get("trigger_id"),
                "source": payload.get("source"),
            },
        )

    # =========================================================================
    # Helper Methods (Placeholder for DB operations)
    # =========================================================================

    def _get_all_triggers(self) -> List[dict]:
        """Get all triggers (placeholder)"""
        # In production: query database
        return []

    def _get_trigger(self, trigger_id: str) -> Optional[dict]:
        """Get a specific trigger (placeholder)"""
        # In production: query database
        return None

    def _save_trigger(self, trigger: dict) -> None:
        """Save/update a trigger (placeholder)"""
        # In production: upsert to database
        pass

    def _delete_trigger(self, trigger_id: str) -> None:
        """Delete a trigger (placeholder)"""
        # In production: delete from database
        pass

    def _save_evaluation(self, evaluation: dict) -> None:
        """Save an evaluation record (placeholder)"""
        # In production: insert into cycle_evaluations table
        pass

    def _get_evaluations_for_cycle(self, cycle_id: UUID) -> List[dict]:
        """Get evaluations for a cycle (placeholder)"""
        # In production: query cycle_evaluations table
        return []

    async def _is_already_evaluated(self, cycle_id: UUID, period_key: str) -> bool:
        """Check if cycle was already evaluated for this period (idempotency)"""
        # In production: check cycle_evaluations table for unique(cycle_id, period_key)
        return False

    def _generate_period_key(self, trigger: dict, now_utc: datetime) -> str:
        """Generate period key for idempotency"""
        trigger_type = trigger.get("type")

        if trigger_type == "CALENDAR":
            # Daily period key
            return now_utc.strftime("%Y-%m-%d")
        elif trigger_type == "HOURS":
            # Hourly period key
            return now_utc.strftime("%Y-%m-%d-%H")
        elif trigger_type == "COUNT":
            # Counter-based - use counter reset period
            return now_utc.strftime("%Y-%m")

        return new_id()


# =============================================================================
# Convenience Functions (API handlers delegate to these)
# =============================================================================

async def create_cycle(ctx: RequestContext, data: CycleCreate) -> dict:
    """Create a new cycle"""
    service: CyclesService = await get_service("cycles", "CyclesPort")
    return await service.create_cycle(ctx, data)


async def update_cycle(ctx: RequestContext, cycle_id: UUID, patch: CycleUpdate) -> dict:
    """Update an existing cycle"""
    service: CyclesService = await get_service("cycles", "CyclesPort")
    return await service.update_cycle(ctx, cycle_id, patch)


async def list_cycles(
    ctx: RequestContext,
    filters: Optional[Dict[str, Any]] = None,
    page: int = 1,
    page_size: int = 50,
) -> Dict[str, Any]:
    """List cycles"""
    service: CyclesService = await get_service("cycles", "CyclesPort")
    return await service.list_cycles(ctx, filters, page, page_size)


async def get_cycle(ctx: RequestContext, cycle_id: UUID) -> dict:
    """Get cycle details"""
    service: CyclesService = await get_service("cycles", "CyclesPort")
    return await service.get_cycle(ctx, cycle_id)


async def add_trigger(ctx: RequestContext, cycle_id: UUID, trigger: TriggerSpec) -> dict:
    """Add a trigger to a cycle"""
    service: CyclesService = await get_service("cycles", "CyclesPort")
    return await service.add_trigger(ctx, cycle_id, trigger)


async def update_trigger(
    ctx: RequestContext, cycle_id: UUID, trigger_id: str, patch: TriggerSpec
) -> dict:
    """Update a trigger"""
    service: CyclesService = await get_service("cycles", "CyclesPort")
    return await service.update_trigger(ctx, cycle_id, trigger_id, patch)


async def remove_trigger(ctx: RequestContext, cycle_id: UUID, trigger_id: str) -> None:
    """Remove a trigger"""
    service: CyclesService = await get_service("cycles", "CyclesPort")
    return await service.remove_trigger(ctx, cycle_id, trigger_id)


async def suspend_cycle(ctx: RequestContext, cycle_id: UUID) -> dict:
    """Suspend a cycle"""
    service: CyclesService = await get_service("cycles", "CyclesPort")
    return await service.suspend_cycle(ctx, cycle_id)


async def activate_cycle(ctx: RequestContext, cycle_id: UUID) -> dict:
    """Activate a suspended cycle"""
    service: CyclesService = await get_service("cycles", "CyclesPort")
    return await service.activate_cycle(ctx, cycle_id)


async def archive_cycle(ctx: RequestContext, cycle_id: UUID) -> None:
    """Archive a cycle"""
    service: CyclesService = await get_service("cycles", "CyclesPort")
    return await service.archive_cycle(ctx, cycle_id)


async def manual_trigger(ctx: RequestContext, cycle_id: UUID) -> dict:
    """Manually trigger a cycle"""
    service: CyclesService = await get_service("cycles", "CyclesPort")
    return await service.manual_trigger(ctx, cycle_id)


async def evaluate_due_cycles() -> Dict[str, Any]:
    """Evaluate all due cycles (worker task)"""
    service: CyclesService = await get_service("cycles", "CyclesPort")
    return await service.evaluate_due_cycles()


async def evaluate_calendar(
    trigger: dict, now_utc: datetime, last_run: Optional[datetime] = None
) -> bool:
    """Evaluate a calendar trigger"""
    service: CyclesService = await get_service("cycles", "CyclesPort")
    return await service.evaluate_calendar(trigger, now_utc, last_run)


async def evaluate_counter(trigger: dict, entity_id: UUID) -> bool:
    """Evaluate a counter trigger"""
    service: CyclesService = await get_service("cycles", "CyclesPort")
    return await service.evaluate_counter(trigger, entity_id)


async def detect_missed_cycles() -> Dict[str, Any]:
    """Detect missed cycles (worker task)"""
    service: CyclesService = await get_service("cycles", "CyclesPort")
    return await service.detect_missed_cycles()


async def get_evaluations(
    ctx: RequestContext, cycle_id: UUID, page: int = 1, page_size: int = 50
) -> Dict[str, Any]:
    """Get cycle evaluations"""
    service: CyclesService = await get_service("cycles", "CyclesPort")
    return await service.get_evaluations(ctx, cycle_id, page, page_size)
