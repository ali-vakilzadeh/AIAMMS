"""
TICKETS Module - Repair Ticketing & Files Management

This module handles:
- Repair ticket creation with payment gate (TENANCY)
- Pool claim/assign workflow
- 5-step flow with 3-loop cap and escalation
- File attachment domain with policy validation
- Manual ingestion flagging for AI processing

Tables: tickets, ticket_reports, ticket_feedbacks, ticket_assignments, ticket_events
Files tables: files, work_order_attachments (join semantics shared with WORKORDERS)
"""

from .service import (
    # Ticket models
    TicketStatus,
    TicketPriority,
    TicketView,
    TicketDetail,
    TicketCreate,
    ClaimRequest,
    AssignRequest,
    ReportSubmit,
    FeedbackSubmit,
    EscalateRequest,
    ManagerDecision,
    
    # File models
    FilePurpose,
    IngestionStatus,
    FileView,
    FileUploadMeta,
    DupDecision,
    
    # Services
    TicketService,
    FileService,
    
    # Router
    router,
    
    # Module
    TicketsModule,
    FilesModule,
)

__all__ = [
    # Enums
    "TicketStatus",
    "TicketPriority",
    "FilePurpose",
    "IngestionStatus",
    
    # Models
    "TicketView",
    "TicketDetail",
    "TicketCreate",
    "ClaimRequest",
    "AssignRequest",
    "ReportSubmit",
    "FeedbackSubmit",
    "EscalateRequest",
    "ManagerDecision",
    "FileView",
    "FileUploadMeta",
    "DupDecision",
    
    # Services
    "TicketService",
    "FileService",
    
    # Router
    "router",
    
    # Modules
    "TicketsModule",
    "FilesModule",
]
