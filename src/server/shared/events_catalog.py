"""
Shared events catalog - All domain events used across the system.

Events are dot-delimited strings. This module defines all event names
used by publishers and subscribers.
"""

from enum import Enum


class Events(str, Enum):
    """All domain events in the system."""
    
    # Core module events
    MODULE_HEALTH_CHANGED = "module.health_changed"
    
    # Auth module events
    USER_REGISTERED = "user.registered"
    USER_VERIFIED = "user.verified"
    USER_LOGGED_IN = "user.logged_in"
    USER_PASSWORD_RESET = "user.password_reset"
    USER_ROLE_CHANGED = "user.role_changed"
    USER_DEACTIVATED = "user.deactivated"
    
    # Organization/Tenancy events
    ORG_CREATED = "org.created"
    ORG_UPDATED = "org.updated"
    INVITATION_SENT = "invitation.sent"
    INVITATION_ACCEPTED = "invitation.accepted"
    INVITATION_EXPIRED = "invitation.expired"
    MEMBERSHIP_CHANGED = "membership.changed"
    PAYMENT_OVERDUE = "payment.overdue"
    PAYMENT_CLEARED = "payment.cleared"
    
    # Asset events
    ASSET_ZONE_CREATED = "asset.zone.created"
    ASSET_ZONE_UPDATED = "asset.zone.updated"
    ASSET_ZONE_DECOMMISSIONED = "asset.zone.decommissioned"
    ASSET_ZONE_CLONED = "asset.zone.cloned"
    ASSET_SYSTEM_CREATED = "asset.system.created"
    ASSET_SYSTEM_UPDATED = "asset.system.updated"
    ASSET_SYSTEM_DECOMMISSIONED = "asset.system.decommissioned"
    ASSET_SERVICE_POINT_CREATED = "asset.service_point.created"
    ASSET_SERVICE_POINT_UPDATED = "asset.service_point.updated"
    ASSET_SERVICE_POINT_DECOMMISSIONED = "asset.service_point.decommissioned"
    COUNTER_LOGGED = "counter.logged"
    COUNTER_RESET = "counter.reset"
    SAFETY_FLAG_CHANGED = "safety_flag.changed"
    
    # Template events
    TEMPLATE_CREATED = "template.created"
    TEMPLATE_UPDATED = "template.updated"
    TEMPLATE_ARCHIVED = "template.archived"
    
    # Cycle events
    CYCLE_CREATED = "cycle.created"
    CYCLE_UPDATED = "cycle.updated"
    CYCLE_SUSPENDED = "cycle.suspended"
    CYCLE_ACTIVATED = "cycle.activated"
    CYCLE_DUE = "cycle.due"
    CYCLE_MISSED = "cycle.missed"
    CYCLE_EVAL_FAILED = "cycle.eval_failed"
    
    # Work Order events
    WORK_ORDER_GENERATED = "work_order.generated"
    WORK_ORDER_ACKNOWLEDGED = "work_order.acknowledged"
    WORK_ORDER_REJECTED = "work_order.rejected"
    WORK_ORDER_SNOOZED = "work_order.snoozed"
    WORK_ORDER_RESUMED = "work_order.resumed"
    WORK_ORDER_BLOCKED = "work_order.blocked"
    WORK_ORDER_COMPLETED = "work_order.completed"
    WORK_ORDER_CLOSED = "work_order.closed"
    WORK_ORDER_OVERDUE = "work_order.overdue"
    WO_ITEM_UPDATED = "wo_item.updated"
    WO_ITEM_MEASURED = "wo_item.measured"
    WO_ITEM_SIGNED = "wo_item.signed"
    
    # Ticket events
    TICKET_CREATED = "ticket.created"
    TICKET_CLAIMED = "ticket.claimed"
    TICKET_ASSIGNED = "ticket.assigned"
    TICKET_REPORT_SUBMITTED = "ticket.report_submitted"
    TICKET_FEEDBACK_REQUESTED = "ticket.feedback_requested"
    TICKET_ACCEPTED = "ticket.accepted"
    TICKET_ESCALATED = "ticket.escalated"
    TICKET_CLOSED = "ticket.closed"
    
    # File events
    FILE_UPLOADED = "file.uploaded"
    FILE_DELETED = "file.deleted"
    MANUAL_INGESTION_REQUESTED = "manual.ingestion_requested"
    
    # AI events
    AI_CHECKLIST_COMPLETED = "ai.checklist_completed"
    AI_CHECKLIST_FAILED = "ai.checklist_failed"
    AI_INGESTION_COMPLETED = "ai.ingestion_completed"
    AI_INGESTION_FAILED = "ai.ingestion_failed"
    AI_ASSISTANT_ANSWERED = "ai.assistant_answered"
    
    # Notification events (internal)
    NOTIFICATION_CREATED = "notification.created"
    NOTIFICATION_EXPIRED = "notification.expired"
    
    # Export events
    EXPORT_READY = "export.ready"


# Event metadata for documentation
EVENT_METADATA = {
    Events.MODULE_HEALTH_CHANGED.value: {
        "description": "Module health status changed",
        "payload": {"module": str, "old_status": str, "new_status": str, "checks": list},
        "consumers": ["observability", "notify"],
    },
    Events.USER_REGISTERED.value: {
        "description": "New user registered (unverified)",
        "payload": {"user_id": str, "email": str},
        "consumers": ["audit", "notify"],
    },
    Events.CYCLE_DUE.value: {
        "description": "Maintenance cycle is due - triggers work order generation",
        "payload": {"cycle_id": str, "trigger_id": str, "period_key": str, "source": str},
        "consumers": ["workorders", "notify"],
    },
    Events.WORK_ORDER_GENERATED.value: {
        "description": "New work order generated from cycle",
        "payload": {"work_order_id": str, "cycle_id": str, "node_id": str, "assignee": str},
        "consumers": ["notify", "audit"],
    },
}


def get_event_consumers(event_name: str) -> list[str]:
    """Get list of modules that consume this event."""
    meta = EVENT_METADATA.get(event_name, {})
    return meta.get("consumers", [])


def get_event_description(event_name: str) -> str:
    """Get human-readable description of an event."""
    meta = EVENT_METADATA.get(event_name, {})
    return meta.get("description", "No description available")
