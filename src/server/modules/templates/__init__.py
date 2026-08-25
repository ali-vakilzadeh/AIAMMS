"""
TEMPLATES Module - Workflows & Checklists

Provides workflow and checklist template management with:
- Auto-generated unique codes
- Item-level validation (acyclic graphs, measurement types)
- Immutable snapshots for work order generation
- Text search within items
- Soft-delete/archiving with reference checks
"""

from .service import (
    TemplatesModule,
    create_workflow,
    get_workflow,
    update_workflow,
    list_workflows,
    archive_workflow,
    add_workflow_item,
    update_workflow_item,
    delete_workflow_item,
    create_checklist,
    update_checklist,
    list_checklists,
    archive_checklist,
    add_checklist_item,
    update_checklist_item,
    delete_checklist_item,
    search_workflows,
    search_checklists,
    snapshot,
    validate_item_graph,
    WorkflowItem,
    ChecklistItem,
    TemplateSnapshot,
    WorkItemSnapshot,
    SearchHit,
)

__all__ = [
    "TemplatesModule",
    "create_workflow",
    "get_workflow",
    "update_workflow",
    "list_workflows",
    "archive_workflow",
    "add_workflow_item",
    "update_workflow_item",
    "delete_workflow_item",
    "create_checklist",
    "update_checklist",
    "list_checklists",
    "archive_checklist",
    "add_checklist_item",
    "update_checklist_item",
    "delete_checklist_item",
    "search_workflows",
    "search_checklists",
    "snapshot",
    "validate_item_graph",
    "WorkflowItem",
    "ChecklistItem",
    "TemplateSnapshot",
    "WorkItemSnapshot",
    "SearchHit",
]
