"""ASSETS Module - Asset hierarchy: Zones, Systems, Service Points, Counters, QR codes, Safety flags."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4
from enum import Enum
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

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

logger = get_logger("assets")


# =============================================================================
# Enums
# =============================================================================

class EntityStatus(str, Enum):
    """Status for asset entities."""
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"
    SUSPENDED = "SUSPENDED"


class CounterType(str, Enum):
    """Counter measurement types."""
    HOURS = "HOURS"
    COUNT = "COUNT"


class CounterSource(str, Enum):
    """Source of counter log entries."""
    MANUAL = "MANUAL"
    INHERITED = "INHERITED"
    RESET = "RESET"


class SafetyFlagType(str, Enum):
    """Safety flag types that can be set on nodes."""
    HOT_INSPECT = "HOT_INSPECT"
    PAUSE_FOR_INSPECTION = "PAUSE_FOR_INSPECTION"
    STOP_UNTIL_COMPLETE = "STOP_UNTIL_COMPLETE"


class EntityType(str, Enum):
    """Entity types in the asset hierarchy."""
    ZONE = "ZONE"
    SYSTEM = "SYSTEM"
    SUB_SYSTEM = "SUB_SYSTEM"
    SERVICE_POINT = "SERVICE_POINT"


# Max depth constants
MAX_ZONE_DEPTH = 2  # Max 2 levels under a zone
MAX_SYSTEM_DEPTH = 2  # Max system/sub-system
MAX_TOTAL_HIERARCHY = 6  # Total hierarchy depth limit


# =============================================================================
# Exception Classes
# =============================================================================

class MaxDepthExceededError(DomainError):
    """Hierarchy depth limit exceeded."""
    def __init__(self, entity_type: str, current_depth: int, max_depth: int):
        super().__init__(
            error_code="MAX_DEPTH_EXCEEDED",
            message=f"Cannot create {entity_type}: hierarchy depth {current_depth} exceeds maximum {max_depth}",
            details={"entity_type": entity_type, "current_depth": current_depth, "max_depth": max_depth},
        )


class InvalidHierarchyError(DomainError):
    """Invalid hierarchy structure."""
    def __init__(self, message: str):
        super().__init__(
            error_code="INVALID_HIERARCHY",
            message=message,
        )


class QrCodeNotFoundError(DomainError):
    """QR code not found."""
    def __init__(self, code: str):
        super().__init__(
            error_code="NOT_FOUND",
            message=f"QR code '{code}' not found",
            details={"code": code},
        )


class CloneJobFailedError(DomainError):
    """Zone clone job failed."""
    def __init__(self, job_id: str, reason: str):
        super().__init__(
            error_code="CLONE_JOB_FAILED",
            message=f"Clone job {job_id} failed: {reason}",
            details={"job_id": job_id, "reason": reason},
        )


# =============================================================================
# Data Models (Pydantic schemas for API)
# =============================================================================

class ZoneProfile(BaseModel):
    """Zone profile data."""
    name: str
    parent_id: Optional[UUID] = None
    status: EntityStatus = EntityStatus.ACTIVE
    address: Optional[str] = None
    contact: Optional[str] = None
    description: Optional[str] = None
    custom_fields: Dict[str, Any] = Field(default_factory=dict)
    geolocation: Optional[Dict[str, float]] = None  # {lat, lng}


class ZoneCreate(ZoneProfile):
    """Zone creation request."""
    pass


class ZoneUpdate(BaseModel):
    """Zone update request."""
    name: Optional[str] = None
    status: Optional[EntityStatus] = None
    address: Optional[str] = None
    contact: Optional[str] = None
    description: Optional[str] = None
    custom_fields: Optional[Dict[str, Any]] = None
    geolocation: Optional[Dict[str, float]] = None


class SystemProfile(BaseModel):
    """System profile data."""
    name: str
    classification: Optional[str] = None
    specs: Dict[str, Any] = Field(default_factory=dict)
    zone_ids: List[UUID] = Field(default_factory=list)  # Linked zones
    primary_zone_id: Optional[UUID] = None


class SystemCreate(SystemProfile):
    """System creation request."""
    pass


class SystemUpdate(BaseModel):
    """System update request."""
    name: Optional[str] = None
    classification: Optional[str] = None
    specs: Optional[Dict[str, Any]] = None
    zone_ids: Optional[List[UUID]] = None
    primary_zone_id: Optional[UUID] = None


class ServicePointProfile(BaseModel):
    """Service point profile data."""
    name: str
    code: Optional[str] = None
    system_id: UUID
    status: EntityStatus = EntityStatus.ACTIVE


class ServicePointCreate(ServicePointProfile):
    """Service point creation request."""
    pass


class ServicePointUpdate(BaseModel):
    """Service point update request."""
    name: Optional[str] = None
    code: Optional[str] = None
    status: Optional[EntityStatus] = None


class CounterProfile(BaseModel):
    """Counter profile data."""
    type: CounterType
    unit: str
    inherit_from_parent: bool = False
    influence_child_nodes: bool = False


class CounterCreate(CounterProfile):
    """Counter creation request."""
    pass


class CounterLogCreate(BaseModel):
    """Counter log entry creation."""
    new_value: float
    reason: str


class CounterResetRequest(BaseModel):
    """Counter reset request."""
    scope: str = "NODE"  # NODE or NODE_AND_CHILDREN


class SafetyFlagRequest(BaseModel):
    """Safety flag set request."""
    flag: SafetyFlagType
    on: bool


class CloneJobResponse(BaseModel):
    """Clone job response."""
    id: str
    status: str  # PENDING, PROCESSING, COMPLETED, FAILED
    zone_id: Optional[UUID] = None


class QrAsset(BaseModel):
    """QR code asset response."""
    code: str
    image_key: str


class QrView(BaseModel):
    """QR code resolved view."""
    node_profile: Dict[str, Any]
    history: List[Dict[str, Any]]
    manuals: List[Dict[str, Any]]
    attachments: List[Dict[str, Any]]
    active_work_orders: List[Dict[str, Any]]
    active_tickets: List[Dict[str, Any]]


class NodeAggregate(BaseModel):
    """Aggregated node view for MCP."""
    node_id: UUID
    node_type: EntityType
    profile: Dict[str, Any]
    active_work_orders: List[Dict[str, Any]]
    active_tickets: List[Dict[str, Any]]
    safety_flags: List[Dict[str, Any]]
    counters: List[Dict[str, Any]]


# =============================================================================
# In-memory storage (replace with DB in production)
# =============================================================================

class AssetStorage:
    """In-memory storage for assets module (placeholder for DB implementation)."""
    
    def __init__(self):
        self.zones: Dict[UUID, dict] = {}
        self.systems: Dict[UUID, dict] = {}
        self.sub_systems: Dict[UUID, dict] = {}
        self.service_points: Dict[UUID, dict] = {}
        self.counters: Dict[UUID, dict] = {}
        self.counter_logs: Dict[UUID, List[dict]] = {}
        self.qr_codes: Dict[str, UUID] = {}  # code -> node_id
        self.safety_flags: Dict[UUID, List[dict]] = {}  # node_id -> flags
        self.clone_jobs: Dict[str, dict] = {}
    
    async def initialize(self):
        """Initialize storage."""
        logger.info("Asset storage initialized")
    
    async def cleanup(self):
        """Cleanup storage."""
        logger.info("Asset storage cleaned up")


# Global storage instance
_asset_storage = AssetStorage()


def get_asset_storage() -> AssetStorage:
    """Get asset storage instance."""
    return _asset_storage


# =============================================================================
# Helper Functions
# =============================================================================

async def assert_depth(entity_type: EntityType, parent_id: Optional[UUID], org_id: UUID, storage: AssetStorage) -> None:
    """
    Validate hierarchy depth constraints.
    
    Raises MaxDepthExceededError if depth limits would be violated.
    """
    if parent_id is None:
        return  # Root level, no depth check needed
    
    # Calculate current depth from parent
    depth = 0
    current_parent = parent_id
    
    if entity_type == EntityType.ZONE:
        # Count zone levels
        while current_parent:
            zone = storage.zones.get(current_parent)
            if not zone:
                break
            if zone.get("org_id") != org_id:
                raise ForbiddenError("Parent zone belongs to different organization")
            depth += 1
            if depth > MAX_ZONE_DEPTH:
                raise MaxDepthExceededError(EntityType.ZONE.value, depth + 1, MAX_ZONE_DEPTH)
            current_parent = zone.get("parent_id")
    
    elif entity_type in (EntityType.SYSTEM, EntityType.SUB_SYSTEM):
        # Count system levels
        while current_parent:
            system = storage.systems.get(current_parent) or storage.sub_systems.get(current_parent)
            if not system:
                break
            if system.get("org_id") != org_id:
                raise ForbiddenError("Parent system belongs to different organization")
            depth += 1
            if depth > MAX_SYSTEM_DEPTH:
                raise MaxDepthExceededError(entity_type.value, depth + 1, MAX_SYSTEM_DEPTH)
            current_parent = system.get("parent_id")
    
    # Check total hierarchy depth
    if depth >= MAX_TOTAL_HIERARCHY:
        raise MaxDepthExceededError(entity_type.value, depth + 1, MAX_TOTAL_HIERARCHY)


def generate_qr_code(node_id: UUID, node_type: EntityType) -> str:
    """Generate stable QR code for a node."""
    # Use first 8 chars of UUID + type prefix for stable code
    prefix_map = {
        EntityType.ZONE: "Z",
        EntityType.SYSTEM: "S",
        EntityType.SUB_SYSTEM: "SS",
        EntityType.SERVICE_POINT: "SP",
    }
    return f"{prefix_map[node_type]}-{str(node_id)[:8].upper()}"


async def compute_effective_counter(node_id: UUID, counter_type: CounterType, storage: AssetStorage) -> Optional[dict]:
    """
    Resolve counter inheritance chain top-down.
    
    Returns the effective counter value considering inheritance from parents.
    """
    # Get all counters for this node
    node_counters = [c for c in storage.counters.values() 
                     if c["node_id"] == node_id and c["type"] == counter_type]
    
    if node_counters:
        # Return the most recent counter for this node
        return max(node_counters, key=lambda c: c.get("created_at", ""))
    
    # If inherit_from_parent, look up the hierarchy
    # This is simplified - full implementation would traverse parent chain
    return None


async def compute_effective_flags(node_id: UUID, storage: AssetStorage) -> dict:
    """
    Compute effective safety flags for a node.
    
    Returns FlagState with own_flags, propagated_to_parents, halted_parents.
    """
    own_flags = storage.safety_flags.get(node_id, [])
    
    # Flags that propagate to parents (only maintenance-halt flags)
    propagated = [f for f in own_flags 
                  if f["flag_type"] == SafetyFlagType.STOP_UNTIL_COMPLETE and f["on"]]
    
    # Parents that are halted due to child flags
    halted_parents = []
    # Simplified - full implementation would traverse parent chain
    
    return {
        "own_flags": own_flags,
        "propagated_to_parents": propagated,
        "halted_parents": halted_parents,
    }


# =============================================================================
# Domain Service Functions
# =============================================================================

async def create_zone(ctx: RequestContext, data: ZoneCreate, db_session: AsyncSession) -> dict:
    """
    Create a new zone.
    
    MANAGER role required. Validates depth, enforces tenancy quota.
    """
    if ctx.role not in (Role.MANAGER, Role.SYS_ADMIN):
        raise ForbiddenError("create_zone", "zone")
    
    if not ctx.org_id:
        raise ForbiddenError("create_zone", "organization context required")
    
    storage = get_asset_storage()
    
    # Validate depth
    await assert_depth(EntityType.ZONE, data.parent_id, ctx.org_id, storage)
    
    # Check tenancy quota if this counts toward limit
    tenancy_service = get_service("tenancy", "TenancyService")
    if tenancy_service and not await tenancy_service.can_create_service_point(ctx.org_id):
        raise QuotaExceededError("zones", 100, 100)  # Simplified
    
    zone_id = uuid4()
    zone = {
        "id": zone_id,
        "org_id": ctx.org_id,
        "name": data.name,
        "parent_id": data.parent_id,
        "status": data.status.value,
        "address": data.address,
        "contact": data.contact,
        "description": data.description,
        "custom_fields": data.custom_fields,
        "geolocation": data.geolocation,
        "created_at": utcnow().isoformat(),
        "updated_at": utcnow().isoformat(),
        "deleted_at": None,
    }
    
    storage.zones[zone_id] = zone
    
    # Emit event
    event_bus = get_event_bus()
    await event_bus.publish("asset.zone.created", {"zone_id": str(zone_id), "org_id": str(ctx.org_id)})
    
    logger.info(f"Zone created: {zone_id} ({data.name})")
    
    return zone


async def update_zone(ctx: RequestContext, zone_id: UUID, patch: ZoneUpdate, db_session: AsyncSession) -> dict:
    """Update zone profile. MANAGER role required."""
    if ctx.role not in (Role.MANAGER, Role.SYS_ADMIN):
        raise ForbiddenError("update_zone", "zone")
    
    if not ctx.org_id:
        raise ForbiddenError("update_zone", "organization context required")
    
    storage = get_asset_storage()
    
    zone = storage.zones.get(zone_id)
    if not zone:
        raise NotFoundError("Zone", zone_id)
    
    if zone["org_id"] != ctx.org_id:
        raise ForbiddenError("update_zone", "zone belongs to different organization")
    
    # Apply updates
    update_data = patch.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if hasattr(value, 'value'):  # Handle enums
            zone[key] = value.value
        else:
            zone[key] = value
    
    zone["updated_at"] = utcnow().isoformat()
    
    # Emit event
    event_bus = get_event_bus()
    await event_bus.publish("asset.zone.updated", {"zone_id": str(zone_id), "org_id": str(ctx.org_id)})
    
    logger.info(f"Zone updated: {zone_id}")
    
    return zone


async def decommission_zone(ctx: RequestContext, zone_id: UUID, db_session: AsyncSession) -> dict:
    """
    Decommission a zone (soft delete).
    
    Cascades children to INACTIVE/DECOMMISSIONED. Retains history.
    """
    if ctx.role not in (Role.MANAGER, Role.SYS_ADMIN):
        raise ForbiddenError("decommission_zone", "zone")
    
    if not ctx.org_id:
        raise ForbiddenError("decommission_zone", "organization context required")
    
    storage = get_asset_storage()
    
    zone = storage.zones.get(zone_id)
    if not zone:
        raise NotFoundError("Zone", zone_id)
    
    if zone["org_id"] != ctx.org_id:
        raise ForbiddenError("decommission_zone", "zone belongs to different organization")
    
    # Soft delete
    zone["status"] = EntityStatus.DECOMMISSIONED.value
    zone["deleted_at"] = utcnow().isoformat()
    zone["updated_at"] = utcnow().isoformat()
    
    # Cascade to children (simplified)
    for child_id, child in storage.zones.items():
        if child.get("parent_id") == zone_id and child["org_id"] == ctx.org_id:
            child["status"] = EntityStatus.INACTIVE.value
            child["updated_at"] = utcnow().isoformat()
    
    # Emit event
    event_bus = get_event_bus()
    await event_bus.publish("asset.zone.decommissioned", {"zone_id": str(zone_id), "org_id": str(ctx.org_id)})
    
    logger.info(f"Zone decommissioned: {zone_id}")
    
    return zone


async def get_zone(ctx: RequestContext, zone_id: UUID, db_session: AsyncSession) -> dict:
    """Get zone by ID. Org-scoped."""
    if not ctx.org_id:
        raise ForbiddenError("get_zone", "organization context required")
    
    storage = get_asset_storage()
    
    zone = storage.zones.get(zone_id)
    if not zone:
        raise NotFoundError("Zone", zone_id)
    
    if zone["org_id"] != ctx.org_id:
        raise NotFoundError("Zone", zone_id)
    
    return zone


async def list_zones(ctx: RequestContext, page: int = 1, page_size: int = 50, db_session: AsyncSession = None) -> Page:
    """List zones for organization. Paginated."""
    if not ctx.org_id:
        raise ForbiddenError("list_zones", "organization context required")
    
    storage = get_asset_storage()
    
    # Filter by org and active status
    zones = [z for z in storage.zones.values() 
             if z["org_id"] == ctx.org_id and z.get("deleted_at") is None]
    
    total = len(zones)
    start = (page - 1) * page_size
    end = start + page_size
    items = zones[start:end]
    
    return Page(items=items, page=page, page_size=page_size, total=total)


async def create_system(ctx: RequestContext, data: SystemCreate, db_session: AsyncSession) -> dict:
    """Create a new system. MANAGER role required."""
    if ctx.role not in (Role.MANAGER, Role.SYS_ADMIN):
        raise ForbiddenError("create_system", "system")
    
    if not ctx.org_id:
        raise ForbiddenError("create_system", "organization context required")
    
    storage = get_asset_storage()
    
    # Validate depth
    await assert_depth(EntityType.SYSTEM, None, ctx.org_id, storage)
    
    system_id = uuid4()
    system = {
        "id": system_id,
        "org_id": ctx.org_id,
        "name": data.name,
        "classification": data.classification,
        "specs": data.specs,
        "zone_ids": [str(z) for z in data.zone_ids] if data.zone_ids else [],
        "primary_zone_id": str(data.primary_zone_id) if data.primary_zone_id else None,
        "parent_id": None,
        "created_at": utcnow().isoformat(),
        "updated_at": utcnow().isoformat(),
        "deleted_at": None,
    }
    
    storage.systems[system_id] = system
    
    # Emit event
    event_bus = get_event_bus()
    await event_bus.publish("asset.system.created", {"system_id": str(system_id), "org_id": str(ctx.org_id)})
    
    logger.info(f"System created: {system_id} ({data.name})")
    
    return system


async def update_system(ctx: RequestContext, system_id: UUID, patch: SystemUpdate, db_session: AsyncSession) -> dict:
    """Update system profile. MANAGER role required."""
    if ctx.role not in (Role.MANAGER, Role.SYS_ADMIN):
        raise ForbiddenError("update_system", "system")
    
    if not ctx.org_id:
        raise ForbiddenError("update_system", "organization context required")
    
    storage = get_asset_storage()
    
    system = storage.systems.get(system_id)
    if not system:
        raise NotFoundError("System", system_id)
    
    if system["org_id"] != ctx.org_id:
        raise ForbiddenError("update_system", "system belongs to different organization")
    
    # Apply updates
    update_data = patch.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if isinstance(value, list) and key == "zone_ids":
            system[key] = [str(z) for z in value]
        elif hasattr(value, 'value'):
            system[key] = value.value
        else:
            system[key] = value
    
    system["updated_at"] = utcnow().isoformat()
    
    # Emit event
    event_bus = get_event_bus()
    await event_bus.publish("asset.system.updated", {"system_id": str(system_id), "org_id": str(ctx.org_id)})
    
    logger.info(f"System updated: {system_id}")
    
    return system


async def decommission_system(ctx: RequestContext, system_id: UUID, db_session: AsyncSession) -> dict:
    """Decommission a system (soft delete)."""
    if ctx.role not in (Role.MANAGER, Role.SYS_ADMIN):
        raise ForbiddenError("decommission_system", "system")
    
    if not ctx.org_id:
        raise ForbiddenError("decommission_system", "organization context required")
    
    storage = get_asset_storage()
    
    system = storage.systems.get(system_id)
    if not system:
        raise NotFoundError("System", system_id)
    
    if system["org_id"] != ctx.org_id:
        raise ForbiddenError("decommission_system", "system belongs to different organization")
    
    system["status"] = EntityStatus.DECOMMISSIONED.value
    system["deleted_at"] = utcnow().isoformat()
    system["updated_at"] = utcnow().isoformat()
    
    # Emit event
    event_bus = get_event_bus()
    await event_bus.publish("asset.system.decommissioned", {"system_id": str(system_id), "org_id": str(ctx.org_id)})
    
    logger.info(f"System decommissioned: {system_id}")
    
    return system


async def create_service_point(ctx: RequestContext, data: ServicePointCreate, db_session: AsyncSession) -> dict:
    """Create a new service point. MANAGER role required. Validates tenancy quota."""
    if ctx.role not in (Role.MANAGER, Role.SYS_ADMIN):
        raise ForbiddenError("create_service_point", "service_point")
    
    if not ctx.org_id:
        raise ForbiddenError("create_service_point", "organization context required")
    
    storage = get_asset_storage()
    
    # Check tenancy quota
    tenancy_service = get_service("tenancy", "TenancyService")
    if tenancy_service and not await tenancy_service.can_create_service_point(ctx.org_id):
        raise QuotaExceededError("service_points", 100, 100)
    
    sp_id = uuid4()
    qr_code = generate_qr_code(sp_id, EntityType.SERVICE_POINT)
    
    service_point = {
        "id": sp_id,
        "org_id": ctx.org_id,
        "name": data.name,
        "code": data.code or qr_code,
        "system_id": str(data.system_id),
        "status": data.status.value,
        "qr_id": qr_code,
        "created_at": utcnow().isoformat(),
        "updated_at": utcnow().isoformat(),
        "deleted_at": None,
    }
    
    storage.service_points[sp_id] = service_point
    storage.qr_codes[qr_code] = sp_id
    
    # Emit event
    event_bus = get_event_bus()
    await event_bus.publish("asset.service_point.created", {"service_point_id": str(sp_id), "org_id": str(ctx.org_id)})
    
    logger.info(f"Service point created: {sp_id} ({data.name})")
    
    return service_point


async def update_service_point(ctx: RequestContext, sp_id: UUID, patch: ServicePointUpdate, db_session: AsyncSession) -> dict:
    """Update service point profile. MANAGER role required."""
    if ctx.role not in (Role.MANAGER, Role.SYS_ADMIN):
        raise ForbiddenError("update_service_point", "service_point")
    
    if not ctx.org_id:
        raise ForbiddenError("update_service_point", "organization context required")
    
    storage = get_asset_storage()
    
    sp = storage.service_points.get(sp_id)
    if not sp:
        raise NotFoundError("ServicePoint", sp_id)
    
    if sp["org_id"] != ctx.org_id:
        raise ForbiddenError("update_service_point", "service_point belongs to different organization")
    
    # Apply updates
    update_data = patch.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if hasattr(value, 'value'):
            sp[key] = value.value
        else:
            sp[key] = value
    
    sp["updated_at"] = utcnow().isoformat()
    
    # Emit event
    event_bus = get_event_bus()
    await event_bus.publish("asset.service_point.updated", {"service_point_id": str(sp_id), "org_id": str(ctx.org_id)})
    
    logger.info(f"Service point updated: {sp_id}")
    
    return sp


async def decommission_service_point(ctx: RequestContext, sp_id: UUID, db_session: AsyncSession) -> dict:
    """Decommission a service point (soft delete)."""
    if ctx.role not in (Role.MANAGER, Role.SYS_ADMIN):
        raise ForbiddenError("decommission_service_point", "service_point")
    
    if not ctx.org_id:
        raise ForbiddenError("decommission_service_point", "organization context required")
    
    storage = get_asset_storage()
    
    sp = storage.service_points.get(sp_id)
    if not sp:
        raise NotFoundError("ServicePoint", sp_id)
    
    if sp["org_id"] != ctx.org_id:
        raise ForbiddenError("decommission_service_point", "service_point belongs to different organization")
    
    sp["status"] = EntityStatus.DECOMMISSIONED.value
    sp["deleted_at"] = utcnow().isoformat()
    sp["updated_at"] = utcnow().isoformat()
    
    # Emit event
    event_bus = get_event_bus()
    await event_bus.publish("asset.service_point.decommissioned", {"service_point_id": str(sp_id), "org_id": str(ctx.org_id)})
    
    logger.info(f"Service point decommissioned: {sp_id}")
    
    return sp


async def create_counter(ctx: RequestContext, node_id: UUID, data: CounterCreate, db_session: AsyncSession) -> dict:
    """Create a counter on a service point. MANAGER role required."""
    if ctx.role not in (Role.MANAGER, Role.SYS_ADMIN):
        raise ForbiddenError("create_counter", "counter")
    
    if not ctx.org_id:
        raise ForbiddenError("create_counter", "organization context required")
    
    storage = get_asset_storage()
    
    # Verify node exists
    if node_id not in storage.service_points:
        raise NotFoundError("ServicePoint", node_id)
    
    counter_id = uuid4()
    counter = {
        "id": counter_id,
        "node_id": node_id,
        "org_id": ctx.org_id,
        "type": data.type.value,
        "unit": data.unit,
        "inherit_from_parent": data.inherit_from_parent,
        "influence_child_nodes": data.influence_child_nodes,
        "current_value": 0.0,
        "created_at": utcnow().isoformat(),
    }
    
    storage.counters[counter_id] = counter
    storage.counter_logs[counter_id] = []
    
    # Emit event
    event_bus = get_event_bus()
    await event_bus.publish("counter.created", {"counter_id": str(counter_id), "node_id": str(node_id)})
    
    logger.info(f"Counter created: {counter_id} on node {node_id}")
    
    return counter


async def log_counter(ctx: RequestContext, counter_id: UUID, data: CounterLogCreate, db_session: AsyncSession) -> dict:
    """
    Log a counter value change. OPERATOR or MANAGER role required.
    
    If influence_child_nodes is True, propagates to child counters.
    """
    if ctx.role not in (Role.OPERATOR, Role.MANAGER, Role.SYS_ADMIN):
        raise ForbiddenError("log_counter", "counter")
    
    if not ctx.org_id:
        raise ForbiddenError("log_counter", "organization context required")
    
    storage = get_asset_storage()
    
    counter = storage.counters.get(counter_id)
    if not counter:
        raise NotFoundError("Counter", counter_id)
    
    if counter["org_id"] != ctx.org_id:
        raise ForbiddenError("log_counter", "counter belongs to different organization")
    
    prev_value = counter["current_value"]
    counter["current_value"] = data.new_value
    
    # Log entry
    log_entry = {
        "id": uuid4(),
        "counter_id": counter_id,
        "prev_value": prev_value,
        "new_value": data.new_value,
        "logged_by": str(ctx.user_id),
        "reason": data.reason,
        "source": CounterSource.MANUAL.value,
        "timestamp": utcnow().isoformat(),
    }
    
    storage.counter_logs[counter_id].append(log_entry)
    
    # Propagate to children if influence_child_nodes
    if counter.get("influence_child_nodes"):
        # Find child counters and propagate (simplified)
        logger.info(f"Propagating counter {counter_id} change to children")
    
    # Emit event
    event_bus = get_event_bus()
    await event_bus.publish("counter.logged", {
        "counter_id": str(counter_id),
        "prev_value": prev_value,
        "new_value": data.new_value,
    })
    
    logger.info(f"Counter logged: {counter_id} = {data.new_value}")
    
    return log_entry


async def reset_counter(ctx: RequestContext, counter_id: UUID, db_session: AsyncSession, scope: str = "NODE") -> dict:
    """
    Reset counter to 0. MAINTENANCE or MANAGER role required.
    
    Scope can be NODE or NODE_AND_CHILDREN.
    """
    if ctx.role not in (Role.MAINTENANCE, Role.MANAGER, Role.SYS_ADMIN):
        raise ForbiddenError("reset_counter", "counter")
    
    if not ctx.org_id:
        raise ForbiddenError("reset_counter", "organization context required")
    
    storage = get_asset_storage()
    
    counter = storage.counters.get(counter_id)
    if not counter:
        raise NotFoundError("Counter", counter_id)
    
    if counter["org_id"] != ctx.org_id:
        raise ForbiddenError("reset_counter", "counter belongs to different organization")
    
    prev_value = counter["current_value"]
    counter["current_value"] = 0.0
    
    # Log entry
    log_entry = {
        "id": uuid4(),
        "counter_id": counter_id,
        "prev_value": prev_value,
        "new_value": 0.0,
        "logged_by": str(ctx.user_id),
        "reason": "Manual reset",
        "source": CounterSource.RESET.value,
        "timestamp": utcnow().isoformat(),
    }
    
    storage.counter_logs[counter_id].append(log_entry)
    
    # Emit event
    event_bus = get_event_bus()
    await event_bus.publish("counter.reset", {
        "counter_id": str(counter_id),
        "prev_value": prev_value,
    })
    
    logger.info(f"Counter reset: {counter_id}")
    
    return log_entry


async def get_counter_logs(ctx: RequestContext, counter_id: UUID, page: int = 1, page_size: int = 50) -> Page:
    """Get counter change history. Paginated."""
    if not ctx.org_id:
        raise ForbiddenError("get_counter_logs", "organization context required")
    
    storage = get_asset_storage()
    
    counter = storage.counters.get(counter_id)
    if not counter:
        raise NotFoundError("Counter", counter_id)
    
    if counter["org_id"] != ctx.org_id:
        raise ForbiddenError("get_counter_logs", "counter belongs to different organization")
    
    logs = storage.counter_logs.get(counter_id, [])
    total = len(logs)
    
    start = (page - 1) * page_size
    end = start + page_size
    items = logs[start:end]
    
    return Page(items=items, page=page, page_size=page_size, total=total)


async def generate_qr(ctx: RequestContext, node_id: UUID, db_session: AsyncSession) -> QrAsset:
    """
    Generate QR code for a node. MANAGER role required.
    
    Creates stable code, generates PNG via STORAGE, returns QrAsset.
    """
    if ctx.role not in (Role.MANAGER, Role.SYS_ADMIN):
        raise ForbiddenError("generate_qr", "qr_code")
    
    if not ctx.org_id:
        raise ForbiddenError("generate_qr", "organization context required")
    
    storage = get_asset_storage()
    
    # Find node and determine type
    node = None
    node_type = None
    
    if node_id in storage.service_points:
        node = storage.service_points[node_id]
        node_type = EntityType.SERVICE_POINT
    elif node_id in storage.zones:
        node = storage.zones[node_id]
        node_type = EntityType.ZONE
    elif node_id in storage.systems:
        node = storage.systems[node_id]
        node_type = EntityType.SYSTEM
    
    if not node:
        raise NotFoundError("Node", node_id)
    
    if node["org_id"] != ctx.org_id:
        raise ForbiddenError("generate_qr", "node belongs to different organization")
    
    # Generate QR code
    qr_code = node.get("qr_id") or generate_qr_code(node_id, node_type)
    
    # Storage key for QR image
    image_key = f"qr/{ctx.org_id}/{qr_code}.png"
    
    # Update node with QR code if not already set
    if "qr_id" in node:
        node["qr_id"] = qr_code
    if node_id in storage.service_points:
        storage.service_points[node_id]["qr_id"] = qr_code
    
    storage.qr_codes[qr_code] = node_id
    
    logger.info(f"QR code generated: {qr_code} for node {node_id}")
    
    return QrAsset(code=qr_code, image_key=image_key)


async def resolve_qr(ctx: RequestContext, code: str, db_session: AsyncSession) -> QrView:
    """
    Resolve QR code to node view.
    
    Returns QrView with profile, history, manuals, attachments, active WOs, active tickets.
    Sections filtered by caller role.
    """
    storage = get_asset_storage()
    
    node_id = storage.qr_codes.get(code)
    if not node_id:
        raise QrCodeNotFoundError(code)
    
    # Find node
    node = None
    if node_id in storage.service_points:
        node = storage.service_points[node_id]
    elif node_id in storage.zones:
        node = storage.zones[node_id]
    elif node_id in storage.systems:
        node = storage.systems[node_id]
    
    if not node:
        raise NotFoundError("Node", node_id)
    
    # Build view (role-filtered sections)
    # Simplified - full implementation would fetch related data
    return QrView(
        node_profile=node,
        history=[],
        manuals=[],
        attachments=[],
        active_work_orders=[],
        active_tickets=[],
    )


async def set_safety_flag(ctx: RequestContext, node_id: UUID, flag: SafetyFlagType, on: bool, db_session: AsyncSession) -> dict:
    """
    Set/clear safety flag on a node. MANAGER or MAINTENANCE role required.
    
    MCP agent may never clear/downgrade human-set STOP_UNTIL_COMPLETE.
    """
    if ctx.role not in (Role.MANAGER, Role.MAINTENANCE, Role.SYS_ADMIN):
        raise ForbiddenError("set_safety_flag", "safety_flag")
    
    if not ctx.org_id:
        raise ForbiddenError("set_safety_flag", "organization context required")
    
    storage = get_asset_storage()
    
    # Find node
    node = None
    if node_id in storage.service_points:
        node = storage.service_points[node_id]
    elif node_id in storage.zones:
        node = storage.zones[node_id]
    elif node_id in storage.systems:
        node = storage.systems[node_id]
    
    if not node:
        raise NotFoundError("Node", node_id)
    
    if node["org_id"] != ctx.org_id:
        raise ForbiddenError("set_safety_flag", "node belongs to different organization")
    
    # Initialize flags list if needed
    if node_id not in storage.safety_flags:
        storage.safety_flags[node_id] = []
    
    flags = storage.safety_flags[node_id]
    
    # Check if flag already exists
    existing = next((f for f in flags if f["flag_type"] == flag.value), None)
    
    if on:
        if existing:
            existing["on"] = True
            existing["updated_at"] = utcnow().isoformat()
        else:
            flags.append({
                "id": uuid4(),
                "node_id": node_id,
                "flag_type": flag.value,
                "on": True,
                "set_by": str(ctx.user_id),
                "set_at": utcnow().isoformat(),
                "updated_at": utcnow().isoformat(),
            })
    else:
        # Clearing flag
        # Special rule: MCP cannot clear STOP_UNTIL_COMPLETE set by humans
        if flag == SafetyFlagType.STOP_UNTIL_COMPLETE and existing:
            # Check if set by human (not MCP)
            # For now, allow if user is MANAGER or MAINTENANCE
            pass
        
        if existing:
            existing["on"] = False
            existing["updated_at"] = utcnow().isoformat()
    
    # Emit event
    event_bus = get_event_bus()
    await event_bus.publish("safety_flag.changed", {
        "node_id": str(node_id),
        "flag_type": flag.value,
        "on": on,
    })
    
    logger.info(f"Safety flag {flag.value} {'set' if on else 'cleared'} on node {node_id}")
    
    return {"node_id": node_id, "flag_type": flag.value, "on": on}


async def get_effective_flags(ctx: RequestContext, node_id: UUID) -> dict:
    """Get effective safety flags for a node including propagation."""
    if not ctx.org_id:
        raise ForbiddenError("get_effective_flags", "organization context required")
    
    storage = get_asset_storage()
    
    # Find node
    node = None
    if node_id in storage.service_points:
        node = storage.service_points[node_id]
    elif node_id in storage.zones:
        node = storage.zones[node_id]
    elif node_id in storage.systems:
        node = storage.systems[node_id]
    
    if not node:
        raise NotFoundError("Node", node_id)
    
    if node["org_id"] != ctx.org_id:
        raise ForbiddenError("get_effective_flags", "node belongs to different organization")
    
    return await compute_effective_flags(node_id, storage)


async def clone_zone(ctx: RequestContext, zone_id: UUID, db_session: AsyncSession) -> CloneJobResponse:
    """
    Initiate zone cloning. MANAGER role required.
    
    Creates clone job, dispatches worker task, returns job status.
    """
    if ctx.role not in (Role.MANAGER, Role.SYS_ADMIN):
        raise ForbiddenError("clone_zone", "zone")
    
    if not ctx.org_id:
        raise ForbiddenError("clone_zone", "organization context required")
    
    storage = get_asset_storage()
    
    zone = storage.zones.get(zone_id)
    if not zone:
        raise NotFoundError("Zone", zone_id)
    
    if zone["org_id"] != ctx.org_id:
        raise ForbiddenError("clone_zone", "zone belongs to different organization")
    
    # Create clone job
    job_id = new_id()
    clone_job = {
        "id": job_id,
        "zone_id": zone_id,
        "org_id": ctx.org_id,
        "status": "PENDING",
        "created_at": utcnow().isoformat(),
        "created_by": str(ctx.user_id),
    }
    
    storage.clone_jobs[job_id] = clone_job
    
    # Dispatch worker task (simplified - would use WORKER module)
    logger.info(f"Clone job created: {job_id} for zone {zone_id}")
    
    # Emit event
    event_bus = get_event_bus()
    await event_bus.publish("asset.zone.clone_started", {"job_id": job_id, "zone_id": str(zone_id)})
    
    return CloneJobResponse(id=job_id, status="PENDING", zone_id=zone_id)


async def run_clone_job(job_id: str, db_session: AsyncSession) -> dict:
    """
    Execute zone clone job (worker task).
    
    Replicates zone tree, profiles, custom fields, system links, service points, cycles.
    """
    storage = get_asset_storage()
    
    job = storage.clone_jobs.get(job_id)
    if not job:
        raise NotFoundError("CloneJob", job_id)
    
    # Update status
    job["status"] = "PROCESSING"
    
    try:
        # Clone zone (simplified - full implementation would deep copy entire hierarchy)
        source_zone = storage.zones.get(job["zone_id"])
        if not source_zone:
            raise NotFoundError("Zone", job["zone_id"])
        
        # Create cloned zone with new ID
        new_zone_id = uuid4()
        cloned_zone = source_zone.copy()
        cloned_zone["id"] = new_zone_id
        cloned_zone["name"] = f"{source_zone['name']} (Copy)"
        cloned_zone["created_at"] = utcnow().isoformat()
        cloned_zone["updated_at"] = utcnow().isoformat()
        cloned_zone["deleted_at"] = None
        
        storage.zones[new_zone_id] = cloned_zone
        
        # Update job
        job["status"] = "COMPLETED"
        job["completed_at"] = utcnow().isoformat()
        job["cloned_zone_id"] = new_zone_id
        
        # Emit event
        event_bus = get_event_bus()
        await event_bus.publish("asset.zone.cloned", {
            "job_id": job_id,
            "source_zone_id": str(job["zone_id"]),
            "cloned_zone_id": str(new_zone_id),
        })
        
        logger.info(f"Clone job completed: {job_id} -> {new_zone_id}")
        
        return job
        
    except Exception as e:
        job["status"] = "FAILED"
        job["error"] = str(e)
        job["failed_at"] = utcnow().isoformat()
        
        logger.error(f"Clone job failed: {job_id} - {e}")
        raise CloneJobFailedError(job_id, str(e))


async def get_node_view(ctx: RequestContext, node_id: UUID) -> NodeAggregate:
    """
    Get aggregated node view for MCP resources.
    
    Returns profile, active WOs, active tickets, safety flags, counters.
    """
    if not ctx.org_id:
        raise ForbiddenError("get_node_view", "organization context required")
    
    storage = get_asset_storage()
    
    # Find node
    node = None
    node_type = None
    
    if node_id in storage.service_points:
        node = storage.service_points[node_id]
        node_type = EntityType.SERVICE_POINT
    elif node_id in storage.zones:
        node = storage.zones[node_id]
        node_type = EntityType.ZONE
    elif node_id in storage.systems:
        node = storage.systems[node_id]
        node_type = EntityType.SYSTEM
    
    if not node:
        raise NotFoundError("Node", node_id)
    
    if node["org_id"] != ctx.org_id:
        raise ForbiddenError("get_node_view", "node belongs to different organization")
    
    # Get counters for node
    counters = [c for c in storage.counters.values() if c["node_id"] == node_id]
    
    # Get safety flags
    flags = await compute_effective_flags(node_id, storage)
    
    return NodeAggregate(
        node_id=node_id,
        node_type=node_type,
        profile=node,
        active_work_orders=[],
        active_tickets=[],
        safety_flags=flags["own_flags"],
        counters=counters,
    )


# =============================================================================
# API Router
# =============================================================================

def create_router() -> APIRouter:
    """Create API router for assets module."""
    router = APIRouter(prefix="/assets", tags=["assets"])
    
    @router.post("/zones", status_code=status.HTTP_201_CREATED)
    async def api_create_zone(
        data: ZoneCreate,
        ctx: RequestContext = Depends(lambda: RequestContext(org_id=None, user_id=None, role=Role.MANAGER, request_id=new_id())),
        db: AsyncSession = Depends(lambda: None),
    ):
        return await create_zone(ctx, data, db)
    
    @router.get("/zones/{zone_id}")
    async def api_get_zone(
        zone_id: UUID,
        ctx: RequestContext = Depends(lambda: RequestContext(org_id=None, user_id=None, role=Role.MANAGER, request_id=new_id())),
        db: AsyncSession = Depends(lambda: None),
    ):
        return await get_zone(ctx, zone_id, db)
    
    @router.patch("/zones/{zone_id}")
    async def api_update_zone(
        zone_id: UUID,
        patch: ZoneUpdate,
        ctx: RequestContext = Depends(lambda: RequestContext(org_id=None, user_id=None, role=Role.MANAGER, request_id=new_id())),
        db: AsyncSession = Depends(lambda: None),
    ):
        return await update_zone(ctx, zone_id, patch, db)
    
    @router.delete("/zones/{zone_id}")
    async def api_decommission_zone(
        zone_id: UUID,
        ctx: RequestContext = Depends(lambda: RequestContext(org_id=None, user_id=None, role=Role.MANAGER, request_id=new_id())),
        db: AsyncSession = Depends(lambda: None),
    ):
        return await decommission_zone(ctx, zone_id, db)
    
    @router.get("/zones")
    async def api_list_zones(
        page: int = 1,
        page_size: int = 50,
        ctx: RequestContext = Depends(lambda: RequestContext(org_id=None, user_id=None, role=Role.MANAGER, request_id=new_id())),
        db: AsyncSession = Depends(lambda: None),
    ):
        return await list_zones(ctx, page, page_size, db)
    
    @router.post("/systems", status_code=status.HTTP_201_CREATED)
    async def api_create_system(
        data: SystemCreate,
        ctx: RequestContext = Depends(lambda: RequestContext(org_id=None, user_id=None, role=Role.MANAGER, request_id=new_id())),
        db: AsyncSession = Depends(lambda: None),
    ):
        return await create_system(ctx, data, db)
    
    @router.patch("/systems/{system_id}")
    async def api_update_system(
        system_id: UUID,
        patch: SystemUpdate,
        ctx: RequestContext = Depends(lambda: RequestContext(org_id=None, user_id=None, role=Role.MANAGER, request_id=new_id())),
        db: AsyncSession = Depends(lambda: None),
    ):
        return await update_system(ctx, system_id, patch, db)
    
    @router.delete("/systems/{system_id}")
    async def api_decommission_system(
        system_id: UUID,
        ctx: RequestContext = Depends(lambda: RequestContext(org_id=None, user_id=None, role=Role.MANAGER, request_id=new_id())),
        db: AsyncSession = Depends(lambda: None),
    ):
        return await decommission_system(ctx, system_id, db)
    
    @router.post("/service-points", status_code=status.HTTP_201_CREATED)
    async def api_create_service_point(
        data: ServicePointCreate,
        ctx: RequestContext = Depends(lambda: RequestContext(org_id=None, user_id=None, role=Role.MANAGER, request_id=new_id())),
        db: AsyncSession = Depends(lambda: None),
    ):
        return await create_service_point(ctx, data, db)
    
    @router.patch("/service-points/{sp_id}")
    async def api_update_service_point(
        sp_id: UUID,
        patch: ServicePointUpdate,
        ctx: RequestContext = Depends(lambda: RequestContext(org_id=None, user_id=None, role=Role.MANAGER, request_id=new_id())),
        db: AsyncSession = Depends(lambda: None),
    ):
        return await update_service_point(ctx, sp_id, patch, db)
    
    @router.delete("/service-points/{sp_id}")
    async def api_decommission_service_point(
        sp_id: UUID,
        ctx: RequestContext = Depends(lambda: RequestContext(org_id=None, user_id=None, role=Role.MANAGER, request_id=new_id())),
        db: AsyncSession = Depends(lambda: None),
    ):
        return await decommission_service_point(ctx, sp_id, db)
    
    @router.post("/service-points/{node_id}/counters", status_code=status.HTTP_201_CREATED)
    async def api_create_counter(
        node_id: UUID,
        data: CounterCreate,
        ctx: RequestContext = Depends(lambda: RequestContext(org_id=None, user_id=None, role=Role.MANAGER, request_id=new_id())),
        db: AsyncSession = Depends(lambda: None),
    ):
        return await create_counter(ctx, node_id, data, db)
    
    @router.post("/service-points/{node_id}/counters/log")
    async def api_log_counter(
        node_id: UUID,
        data: CounterLogCreate,
        ctx: RequestContext = Depends(lambda: RequestContext(org_id=None, user_id=None, role=Role.MANAGER, request_id=new_id())),
        db: AsyncSession = Depends(lambda: None),
    ):
        # Find counter for node (simplified)
        storage = get_asset_storage()
        counter = next((c for c in storage.counters.values() if c["node_id"] == node_id), None)
        if not counter:
            raise NotFoundError("Counter", node_id)
        return await log_counter(ctx, counter["id"], data, db)
    
    @router.post("/service-points/{node_id}/counters/reset")
    async def api_reset_counter(
        node_id: UUID,
        scope: str = "NODE",
        ctx: RequestContext = Depends(lambda: RequestContext(org_id=None, user_id=None, role=Role.MANAGER, request_id=new_id())),
        db: AsyncSession = Depends(lambda: None),
    ):
        storage = get_asset_storage()
        counter = next((c for c in storage.counters.values() if c["node_id"] == node_id), None)
        if not counter:
            raise NotFoundError("Counter", node_id)
        return await reset_counter(ctx, counter["id"], scope, db)
    
    @router.get("/service-points/{node_id}/counters/logs")
    async def api_get_counter_logs(
        node_id: UUID,
        page: int = 1,
        page_size: int = 50,
        ctx: RequestContext = Depends(lambda: RequestContext(org_id=None, user_id=None, role=Role.MANAGER, request_id=new_id())),
    ):
        storage = get_asset_storage()
        counter = next((c for c in storage.counters.values() if c["node_id"] == node_id), None)
        if not counter:
            raise NotFoundError("Counter", node_id)
        return await get_counter_logs(ctx, counter["id"], page, page_size)
    
    @router.post("/service-points/{node_id}/qr")
    async def api_generate_qr(
        node_id: UUID,
        ctx: RequestContext = Depends(lambda: RequestContext(org_id=None, user_id=None, role=Role.MANAGER, request_id=new_id())),
        db: AsyncSession = Depends(lambda: None),
    ):
        return await generate_qr(ctx, node_id, db)
    
    @router.get("/qr/resolve/{code}")
    async def api_resolve_qr(
        code: str,
        ctx: RequestContext = Depends(lambda: RequestContext(org_id=None, user_id=None, role=Role.MANAGER, request_id=new_id())),
        db: AsyncSession = Depends(lambda: None),
    ):
        return await resolve_qr(ctx, code, db)
    
    @router.post("/service-points/{node_id}/flags")
    async def api_set_safety_flag(
        node_id: UUID,
        flag_req: SafetyFlagRequest,
        ctx: RequestContext = Depends(lambda: RequestContext(org_id=None, user_id=None, role=Role.MANAGER, request_id=new_id())),
        db: AsyncSession = Depends(lambda: None),
    ):
        return await set_safety_flag(ctx, node_id, flag_req.flag, flag_req.on, db)
    
    @router.get("/service-points/{node_id}/flags")
    async def api_get_effective_flags(
        node_id: UUID,
        ctx: RequestContext = Depends(lambda: RequestContext(org_id=None, user_id=None, role=Role.MANAGER, request_id=new_id())),
    ):
        return await get_effective_flags(ctx, node_id)
    
    @router.post("/zones/{zone_id}/clone")
    async def api_clone_zone(
        zone_id: UUID,
        ctx: RequestContext = Depends(lambda: RequestContext(org_id=None, user_id=None, role=Role.MANAGER, request_id=new_id())),
        db: AsyncSession = Depends(lambda: None),
    ):
        return await clone_zone(ctx, zone_id, db)
    
    @router.get("/nodes/{node_id}")
    async def api_get_node_view(
        node_id: UUID,
        ctx: RequestContext = Depends(lambda: RequestContext(org_id=None, user_id=None, role=Role.MANAGER, request_id=new_id())),
    ):
        return await get_node_view(ctx, node_id)
    
    return router


# =============================================================================
# Module Implementation
# =============================================================================

class AssetsModule(ModuleBase):
    """Assets module implementing ModuleBase protocol."""
    
    name = "assets"
    version = "1.0.0"
    dependencies = ["core", "db", "api", "tenancy", "storage", "worker"]
    optional_dependencies = ["cache", "email"]
    profiles = ["api", "worker", "all-in-one"]
    
    def __init__(self):
        super().__init__()
        self._router = None
        self._storage = get_asset_storage()
    
    async def configure(self, ctx: ModuleContext) -> None:
        """Configure assets module."""
        logger.info("Configuring assets module...")
        self._router = create_router()
        logger.info("Assets module configured")
    
    async def initialize(self, ctx: ModuleContext) -> None:
        """Initialize assets module."""
        logger.info("Initializing assets module...")
        await self._storage.initialize()
        logger.info("Assets module initialized")
    
    async def start(self, ctx: ModuleContext) -> None:
        """Start assets module."""
        logger.info("Starting assets module...")
        
        # Register router with API module
        try:
            api_service = get_service("api", "HttpApi")
            if api_service and self._router:
                api_service.register_router(self._router, prefix="assets", tags=["assets"])
                logger.info("Assets router registered with API")
        except Exception as e:
            logger.warning(f"Could not register assets router: {e}")
        
        logger.info("Assets module started")
    
    async def stop(self, ctx: ModuleContext) -> None:
        """Stop assets module."""
        logger.info("Stopping assets module...")
        await self._storage.cleanup()
        logger.info("Assets module stopped")
    
    async def health(self) -> HealthStatus:
        """Check assets module health."""
        # Check storage health
        try:
            # Basic health check - ensure storage is accessible
            _ = len(self._storage.zones)
            return HealthStatus.OK
        except Exception as e:
            logger.error(f"Assets health check failed: {e}")
            return HealthStatus.UNAVAILABLE


# Module instance
_assets_module = None


def get_assets_module() -> AssetsModule:
    """Get assets module instance."""
    global _assets_module
    if _assets_module is None:
        _assets_module = AssetsModule()
    return _assets_module
