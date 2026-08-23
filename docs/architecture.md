================================================================================
OPEN-SOURCE CMMS SAAS - MVP SOFTWARE ARCHITECTURE DOCUMENT
REVISED TO SUPPORT FULL MVP REQUIREMENTS + AI PHASE 1 & PHASE 2
================================================================================

1. SYSTEM OVERVIEW
--------------------------------------------------------------------------------
The system is a multi-tenant, role-based, open-source Computerized Maintenance
Management System (CMMS) delivered as a web-based SaaS.

The MVP shall provide:
- User signup, login, password recovery, and organization membership.
- Organization and multi-tenant management.
- Asset hierarchy management: zones, systems, sub-systems, service points.
- Maintenance and inspection cycles with calendar/hours/count triggers.
- Workflows, checklists, work orders, and repair ticketing.
- Safety / operational flags with parent-structure effects.
- QR / barcode generation, printing, and scanning.
- File attachments and storage abstraction.
- In-app notifications and reporting dashboards.
- AI-assisted checklist generation.
- AI-powered RAG manual assistant for node manuals.

The architecture shall support:
- Desktop, mobile, and tablet browsers.
- Bi-directional UI text entry and RTL/LTR layout support.
- Strict organization-level data isolation.
- Background processing for cycles, notifications, AI, and file ingestion.
- API-first integration and OpenAPI documentation.

2. TECHNOLOGY STACK
--------------------------------------------------------------------------------
Frontend Client:
- React 18+
- TypeScript
- Vite
- Tailwind CSS using logical properties for RTL/LTR support
- React Query for server-state fetching, caching, and invalidation
- HTML5 QR code scanner for field access
- Responsive layout for desktop, tablet, and mobile browsers
- Persistent login using refresh tokens

Backend API:
- Python 3.11+
- FastAPI asynchronous REST API
- SQLAlchemy ORM
- Pydantic validation and serialization
- Celery background workers
- Celery Beat scheduled tasks
- OpenAPI / Swagger documentation generated automatically

MCP Server:
- Python 3.11+ (shared domain layer with FastAPI)
- Official MCP Python SDK (JSON-RPC 2.0)
- Stdio + Streamable HTTP/SSE transports

Database:
- PostgreSQL 15+
- PostgreSQL JSONB for custom fields
- Recursive CTEs for hierarchy traversal
- pgvector extension for AI embeddings used by the RAG assistant

Cache / Queue / Scheduler:
- Redis 7+
- Redis as Celery broker
- Redis for rate limiting
- Redis delayed queues for snooze expiration and scheduled reminders

Storage:
- MinIO or S3-compatible object storage
- Storage abstraction layer allowing local storage or external S3-compatible
  storage
- Pre-signed URLs for secure file access

Email:
- Transactional email abstraction for signup verification and password reset
- SMTP or email API provider
- No operational email notifications in MVP; operational notifications are
  in-app only

AI:
- Text LLM integration for checklist generation
- Text LLM plus RAG integration for manual assistant
- Provider abstraction layer supporting:
  - External OpenAI-compatible API
  - External Anthropic-compatible API
  - Local/self-hosted model via Ollama, vLLM, or compatible inference server
- PDF/text extraction pipeline for RAG ingestion
- pgvector storage for document chunk embeddings

Infrastructure:
- Docker and Docker Compose
- Nginx reverse proxy
- GitHub Actions CI/CD
- Structured logging
- Health check endpoints
- Environment-based configuration

3. HIGH-LEVEL COMPONENT MODEL
--------------------------------------------------------------------------------
The system shall consist of the following major components:

1. React SPA Client
   - User-facing web application.
   - Supports RTL/LTR.
   - Communicates only with backend REST API.
   - Uses QR scanning, dashboards, work orders, tickets, notifications,
     AI checklist generation, and AI manual assistant.

2. FastAPI Backend API
   - Stateless REST API.
   - Performs authentication, authorization, validation, and domain orchestration.
   - Exposes OpenAPI documentation.
   - Enforces tenant isolation and role-based permissions.

3. Background Worker Service
   - Celery workers.
   - Handles cycle evaluation, work order generation, notification expiration,
     invitation expiration, report generation, zone cloning, file ingestion,
     AI embedding generation, AI checklist generation, and AI assistant calls
     when asynchronous processing is preferred.

4. Celery Beat Scheduler
   - Runs periodic jobs:
     - Evaluate due calendar cycles.
     - Detect missed cycles and overdue work orders.
     - Resume snoozed work orders.
     - Expire invitations after 14 days.
     - Archive/expire notifications after 30 days.
     - Refresh dashboard materialized metrics if used.

5. PostgreSQL Database
   - Primary transactional system of record.
   - Stores tenant data, assets, cycles, work orders, tickets, notifications,
     audit logs, AI metadata, and vector embeddings.

6. Redis
   - Celery broker.
   - Rate limiting.
   - Short-lived cache.
   - Delayed queues for snooze and reminders.
   - Distributed locks for background job idempotency.

7. Object Storage
   - Stores uploaded files, manuals, photos, generated QR codes, exports,
     and AI ingestion artifacts.
   - Tenant-prefixed paths or buckets.

8. AI Subsystem
   - Checklist generation service.
   - RAG manual assistant service.
   - Document ingestion pipeline.
   - Prompt management and provider abstraction.
   - AI usage logs and tenant-isolated vector data.

4. MULTI-TENANCY AND DATA ISOLATION
--------------------------------------------------------------------------------
Multi-tenancy shall be enforced at multiple layers.

Database Isolation:
- Every tenant-owned table shall include organization_id.
- All queries shall filter by organization_id.
- PostgreSQL Row-Level Security shall be used as defense-in-depth.
- Application database sessions shall set the current organization context.
- Cross-organization access shall be blocked by default.
- Platform system administrator access shall bypass tenant scope only when
  explicitly required and shall be audited.

API Isolation:
- JWT claims shall include organization_id and role.
- API middleware shall validate that the requested resource belongs to the
  authenticated organization.
- Any attempt to access another organization's data shall return not found or
  forbidden, without leaking resource existence.

- MCP Access: The MCP server authenticates via JWT or scoped API key.
  Every MCP session is bound to one organization_id and one RBAC role.
  SYS_ADMIN is never exposed through MCP. All MCP calls pass through
  the same RLS and org_id filters as REST requests.

Storage Isolation:
- Object storage paths shall be tenant-scoped.
- Example path:
  /org-{organization_id}/attachments/...
  /org-{organization_id}/manuals/...
  /org-{organization_id}/exports/...
- Pre-signed URLs shall be short-lived.

AI Isolation:
- AI embeddings shall include organization_id.
- RAG retrieval shall filter by organization_id and permitted node/document.
- Prompts sent to external providers shall not include organization_id,
  user personal data, or unnecessary tenant identifiers.
- The system shall support configuration for local/self-hosted AI models for
  organizations requiring stricter privacy.

Audit Isolation:
- Audit logs shall record organization_id, user_id, action, entity type,
  entity ID, previous state, new state, timestamp, IP address, and user agent.

5. AUTHENTICATION AND AUTHORIZATION ARCHITECTURE
--------------------------------------------------------------------------------
Authentication:
- Email/password signup.
- Mandatory email verification.
- JWT access token with short lifetime, recommended 15 minutes.
- HttpOnly refresh token with longer lifetime, recommended 7 days.
- Refresh token rotation recommended.
- Persistent login on mobile/tablet web client using refresh token.
- Password recovery via secure time-limited token.
- Password complexity rules enforced.

Authorization:
- Role-Based Access Control enforced at API level.
- Roles:
  - SYS_ADMIN
  - MCP Agent (not a new role): An external AI agent authenticates under one of the four existing org roles. Its permissions are identical to a human user holding that role, with additional safety guardrails (confirmation gates, dry-run, rate limits) defined in Section 24.
  - MANAGER
  - REPORTER
  - OPERATOR
  - MAINTENANCE

Role Enforcement:
- Permissions shall be checked on each endpoint.
- Object-level permissions shall be validated.
- Role changes shall be restricted.
- Deactivated users shall not receive new assignments.
- Deactivated users shall retain historical association for audit and records.

Password Recovery Flow:
1. User requests password reset.
2. System creates a time-limited token.
3. Email is sent through transactional email provider.
4. User opens reset link.
5. API validates token and updates password.
6. Existing sessions may be invalidated.

Email Verification Flow:
1. User signs up.
2. User record is created as unverified.
3. Verification token is emailed.
4. User verifies email.
5. User can fully access the system after organization creation or invitation.

6. ORGANIZATION AND INVITATION ARCHITECTURE
--------------------------------------------------------------------------------
Organization Management:
- Each organization is a separate tenant.
- Organization profile includes:
  - Name
  - Logo
  - Contact information
  - Timezone
  - 2 to 3 custom fields
- The base organization account shall also be treated as a root zone for
  address/contact purposes.

Subscription/Tier Enforcement:
- Organization tier shall be stored with effective dates.
- Tiers:
  - Free: up to 100 service points/nodes.
  - Pro: up to 1000 service points/nodes.
  - Ultimate: unlimited nodes.
- Tier limit shall be enforced when creating service points.
- Structural entities such as zones and systems shall not be limited by tier.
- Node count shall count active service points unless otherwise defined.

Payment State:
- Organization payment status shall be stored.
- Overdue organizations retain access to all features except issuing new
  repair tickets.
- Ticket creation endpoint shall block overdue organizations.
- Other workflows, dashboards, and historical data remain accessible.

Invitations:
- Invitation table stores token, email, organization_id, role, status,
  invited_by, expires_at.
- New user invitation:
  - Secure token emailed.
  - Token expires after 14 days.
  - User signs up and accepts invitation.
- Existing user invitation:
  - Type-to-lookup search by email.
  - Directly add user to organization after acceptance.
- A user belongs to only one organization at a time.
- Accepting a new organization invitation requires leaving or replacing the
  previous organization membership.

7. ASSET HIERARCHY DATA ARCHITECTURE
--------------------------------------------------------------------------------
Logical hierarchy:
Organization
-> Zone
-> Zone Child / Zone Breakdown
-> System
-> Sub-system
-> Service Point / Node

Maximum total hierarchy depth:
- 6 levels.

Zone Rules:
- Zones may be flat or tree.
- Zone tree breakdown limited to 2 levels under zone.
- Zone fields:
  - Name
  - Parent zone
  - Status
  - Address
  - Contact information
  - Description
  - Up to 5 custom fields
  - Optional geolocation profile field
- Zone status examples:
  - ACTIVE
  - INACTIVE
  - UNDER_CONSTRUCTION
  - DECOMMISSIONED

System Rules:
- Systems may span multiple zones.
- System depth maximum 2 levels:
  - System
  - Sub-system
- Systems shall support taxonomy/classification.
- Systems shall support general technical specifications.
- Specific equipment-type technical forms are post-MVP.

Service Point Rules:
- Service point is the atomic maintenance unit.
- Service point fields include:
  - Name
  - Code
  - Parent system/sub-system
  - Lifecycle status
  - QR/barcode identifier
  - Safety flags
  - Counters
  - Attachments
  - Manuals/documents
  - Assigned cycles
  - Spare part placeholders
- Service point lifecycle status:
  - ACTIVE
  - IN_MAINTENANCE
  - DECOMMISSIONED
- Only ACTIVE service points shall generate new work orders or tickets unless
  explicitly allowed by domain rules.

Hierarchy Implementation Options:
- Adjacency list with parent_id.
- Materialized path for faster reads.
- Recursive CTEs for traversal.
- Database triggers or application services to enforce max depth.
- Soft delete shall be used across hierarchy.

Cross-Zone Systems:
- Systems may be associated with multiple zones.
- A many-to-many system_zone_links table shall be used.
- One zone link may be marked primary for canonical navigation.
- Additional zone links allow the system to appear under multiple zones.

Soft Delete and Decommissioning:
- Hard delete is restricted.
- Delete operations shall use soft delete fields:
  - deleted_at
  - is_active
  - lifecycle_status
- Children of a soft-deleted parent inherit inactive/decommissioned state
  for practical access restrictions.
- Historical work orders, tickets, counters, and reports remain available.

Zone Cloning:
- Zone cloning shall replicate:
  - Zone tree structure
  - Profiles
  - Custom fields
  - Systems/sub-system links where applicable
  - Service points
  - Cycles
  - Workflow/checklist assignments
  - Relevant configuration
- Cloning shall be processed as a background job for large zones.
- Clone job states:
  - PENDING
  - PROCESSING
  - COMPLETED
  - FAILED
- New cloned entities shall receive new IDs and unique codes where required.

QR / Barcode Architecture:
- Each service point shall have a stable QR/barcode identifier.
- QR code shall point to a secure application URL or signed lookup token.
- QR generation performed server-side.
- Printable label output via HTML/PDF.
- Scanning uses browser camera and HTML5 scanner.
- Scanning resolves node and displays:
  - Profile
  - Maintenance history
  - Manuals
  - Attachments
  - Active work orders/tickets if permitted by role.

8. SERVICE POINT COUNTER ARCHITECTURE
--------------------------------------------------------------------------------
Counter Types:
- Operation hours.
- Operation count.

Counter Model:
- A service point may have multiple counters.
- Counter fields:
  - Service point ID
  - Counter type
  - Unit
  - Current value
  - Inherit from parent flag
  - Influence child nodes flag
  - Created/updated timestamps

Counter Logs:
- Every counter change shall be logged.
- Counter log fields:
  - Counter ID
  - Previous value
  - New value
  - Logged by user
  - Reason
  - Timestamp
  - Source: MANUAL, INHERITED, RESET, SYSTEM

Counter Permissions:
- Operator and Manager can log hours/counts.
- Maintenance can reset counters where permitted.
- Reset scope:
  - Node only.
  - Node and selected children.
- Reset shall not affect unrelated parents.

Counter Inheritance:
- Top-down inheritance for operation hours/count where configured.
- If influence_child_nodes is true, children cannot override inherited cycle.
- Child counters/cycles do not influence parents.

9. MAINTENANCE CYCLE ENGINE
--------------------------------------------------------------------------------
Cycle Assignment Scope:
- Zone
- System
- Sub-system
- Service point

Cycle Trigger Types:
1. Natural/calendar time
   - Cron-like expressions.
2. Operating hours
   - Based on logged operation hours.
3. Operation count
   - Based on logged operation counts.

Multiple Trigger Logic:
- A cycle may have multiple triggers.
- The first satisfied trigger wins.
- Once triggered, the system creates a work order.
- Trigger evaluation must be idempotent.

Cycle Fields:
- Organization ID
- Target entity type
- Target entity ID
- Code
- Name
- Description
- Assigned workflow or checklist
- Safety flag
- Deadline/grace period
- Deadline behavior:
  - FLAG_CRITICAL_STOP
  - WAIT_UNTIL_COMPLETED
- Launch mode:
  - AUTOMATIC
  - MANUAL
- Automatic launch frequency:
  - Once per day/shift
  - Twice per day/shift
- Suspension flag
- Postpone overhead maintenance flag
- Influence child nodes flag
- Status:
  - ACTIVE
  - SUSPENDED
  - ARCHIVED

Cycle Suspension:
- Managers may suspend a cycle.
- Suspended cycles do not generate work orders.
- Calendar triggers pause until reactivated.

Missed Calendar Cycles:
- If a calendar cycle passes its due date without being triggered, the next
  scheduler evaluation shall generate an overdue work order.
- Overdue work orders shall be visibly flagged.

Cycle Inheritance:
- Top-down inheritance applies to operation hours/count cycles.
- Inheritance does not automatically apply to plans/schedules unless configured.
- Parent cycle changes apply only to newly generated work orders.
- Existing generated work orders preserve their original snapshot.

Cycle Scheduler:
- Celery Beat evaluates cycles periodically.
- Redis or database locks prevent duplicate generation.
- Evaluation job:
  1. Find active cycles.
  2. Skip suspended cycles.
  3. Evaluate calendar triggers.
  4. Evaluate counter triggers.
  5. Apply winner logic.
  6. Generate work order snapshot.
  7. Record evaluation event.
  8. Send in-app notifications.

10. SAFETY / OPERATIONAL FLAG ARCHITECTURE
--------------------------------------------------------------------------------
Supported Flags:
- HOT_INSPECT
- PAUSE_FOR_INSPECTION
- STOP_UNTIL_COMPLETE

Behavior:
- HOT_INSPECT:
  Task may execute while node/parent is running.
- PAUSE_FOR_INSPECTION:
  Parent may continue running but should stop shortly for the task.
- STOP_UNTIL_COMPLETE:
  Parent must stop operating until task is complete.

Propagation:
- Safety flags may affect parent structure.
- Only maintenance halts/safety flags can stop parents.
- Flag propagation shall be calculated by asset state service.
- Flag changes shall be audited.

Operational Impact:
- Work order UI shall display safety flag prominently.
- Parent asset status may show halted or pending maintenance state.
- Dashboards may filter by critical safety flags.

11. WORKFLOW, CHECKLIST, AND WORK ORDER ARCHITECTURE
--------------------------------------------------------------------------------
Template Types:
- Checklist:
  - Inspection only.
  - Flat list of items.
  - Results: Inspected, Pass, Fail.
- Workflow:
  - Instruction sets.
  - Sequential tasks.
  - States:
    - TASK
    - STARTED
    - COMPLETED
    - FAILED
    - PENDING_PREDECESSOR
    - PERFORMED_BY

Template Identification:
- Auto-generated unique code.
- User may modify code.
- System enforces uniqueness within organization.
- No cross-organization sharing.

Template Storage:
- Each workflow/checklist item stored separately.
- Items are searchable.
- Search supports text within individual items.

Work Item Template Fields:
- Activity number
- Predecessor activity number
- Description
- Planned date/time
- Assigned date/time
- Deadline
- Started date/time
- Closed date/time
- Status
- Priority
- Estimated duration
- Actual duration
- Assigned to user/role
- Required skills
- Required certifications
- Required tools
- Required parts placeholder
- Safety permit required
- Risk level
- Location override
- Attachments
- Measurement fields
- Measurement unit
- Measurement data type:
  - NUMERIC
  - TEXT
  - BOOLEAN
- Measurement min threshold
- Measurement max threshold
- Digital signature requirement
- Notes/comments
- Cost fields
- Downtime impact
- Linked ticket ID
- Completion percentage
- Quality check by

Work Order Generation:
- A triggered cycle creates a work order.
- Work order is a dated instance/copy of the assigned workflow/checklist.
- Work order stores snapshot of template items.
- Template changes after generation do not retroactively alter existing work
  orders.

Work Order Fields:
- Work order number
- Unique reference
- Organization ID
- Source cycle ID
- Target asset ID
- Workflow/checklist snapshot
- Issue date/time
- Start date/time
- Finish date/time
- Stop date/time
- Deadline
- Status
- Assigned user/role
- Priority
- Safety flag
- Linked ticket ID
- Completion percentage
- Cost
- Downtime impact
- Attachments
- Notes/comments
- Digital signatures
- Quality check reviewer

Work Order Status Model:
Recommended states:
- GENERATED
- ACKNOWLEDGED
- IN_PROGRESS
- BLOCKED
- SNOOZED
- REJECTED
- OVERDUE
- COMPLETED
- CLOSED

Acknowledgment:
- Automatic upon user viewing the work order.
- Acknowledgment shall be idempotent.
- Viewed-by and first-view timestamp shall be stored.

Rejection:
- Rejection requires description/reason.
- Rejected work orders remain in history.

Snooze:
- Snooze requires description.
- Allowed durations:
  - 1 hour
  - 6 hours
  - 12 hours
  - 1 day
  - 3 days
  - 6 days
- Redis delayed queue or Celery countdown used to reactivate notification.
- Snooze history stored.

Execution Updates:
- Maintenance users can update item states.
- Measurements entered according to data type.
- Automatic pass/fail based on thresholds is post-MVP.
- Threaded comments supported.
- Attachments supported per work order and per item where appropriate.
- Digital signature captured where required.

12. REPAIR TICKETING ARCHITECTURE
--------------------------------------------------------------------------------
Ticket Creation:
- Operator and Manager can create repair tickets.
- Ticket creation disabled for overdue organizations.
- Ticket fields:
  - Ticket number
  - Organization ID
  - Service point ID
  - Created by
  - Report section
  - Description
  - Priority:
    - LOW
    - MEDIUM
    - HIGH
    - CRITICAL
  - Status
  - Attachments
  - Created timestamp

Ticket Assignment:
- New tickets are routed to Maintenance Pool.
- Maintenance users may claim tickets.
- Manager may manually assign tickets to a specific maintenance user.
- Assignment changes are audited.

Ticket Flow State Machine:
Recommended states:
- OPEN
- IN_PROGRESS
- REPORT_SUBMITTED
- ISSUER_FEEDBACK_REQUIRED
- ISSUER_ACCEPTED
- ESCALATED_TO_MANAGER
- CLOSED

5-Step Flow:
1. Ticket issued.
2. Maintenance checks and performs work.
3. Maintenance submits report/feedback.
4. Issuer reviews.
5. Issuer accepts and closes, or sends feedback for correction.

Feedback Loop Limit:
- Steps 3 and 4 may repeat maximum 3 times.
- Loop counter stored on ticket.
- After third failed loop:
  - Ticket becomes ESCALATED_TO_MANAGER.
  - Manager decides:
    - Force close.
    - Require new ticket.
    - Mandate additional action.

Ticket Restrictions:
- Overdue organizations cannot create tickets.
- Existing tickets remain accessible for historical resolution unless policy
  defines otherwise.

13. NOTIFICATION ARCHITECTURE
--------------------------------------------------------------------------------
MVP notification channel:
- In-app system notifications only.
- No email/SMS for operational notifications.
- Email is used only for authentication flows:
  - Email verification
  - Password reset
  - Invitation

Notification Center:
- Persistent notification bell/icon in header.
- Unread count badge.
- Notification list page or dropdown.
- Read/unread state.
- Deep link to relevant entity:
  - Work order
  - Ticket
  - Node
  - Cycle
  - Report

Notification Events:
- New work order assigned.
- Work order overdue.
- Work order snooze expiration.
- Ticket assigned/claimed.
- Ticket report submitted.
- Ticket feedback received.
- Ticket escalated.
- Cycle trigger failure.
- AI manual ingestion completed/failed.
- AI checklist generation completed/failed.

Notification Storage:
- Notification table includes:
  - Organization ID
  - User ID
  - Type
  - Title
  - Body
  - Link
  - Entity type
  - Entity ID
  - Read timestamp
  - Created timestamp
  - Expires timestamp

Notification Retention:
- Notifications expire/archive after 30 days.
- Background job marks or moves expired notifications.

Delivery Mechanism:
- MVP may use polling with React Query.
- Optional server-sent events can be introduced later.
- Persistent login ensures users receive alerts when authenticated.

14. REPORTING AND DASHBOARD ARCHITECTURE
--------------------------------------------------------------------------------
Dashboard Users:
- Manager
- Reporter

Dashboard Requirements:
- Filtering.
- Export.
- Common CMMS KPIs.
- User-level counters for new and active work orders.

Recommended MVP KPIs:
- Overdue work orders.
- Open repair tickets.
- Escalated tickets.
- Work orders by status.
- Planned vs unplanned maintenance.
- Asset downtime where inferable.
- Completion rates.
- Safety flag incidents.
- Open work orders by priority.

User Dashboard:
- Each user sees:
  - Number of new work orders.
  - Number of active work orders.
- Role-specific shortcuts.

Report Implementation:
- Use indexed queries for operational dashboards.
- Optional materialized views for heavier KPIs.
- Celery task generates large exports.
- Export formats:
  - CSV
  - XLSX optional
- Exports stored in tenant-scoped object storage with short-lived download URL.

Audit and Reporting:
- Critical state changes available through audit query for managers/sys admin
  where permitted.
- Reports must respect organization isolation.

15. FILE STORAGE AND ATTACHMENT ARCHITECTURE
--------------------------------------------------------------------------------
Supported Attachment Types:
- Images: JPEG, PNG
- Documents: PDF, TXT, DOCX
- Additional document types may be allowed by configuration.

Upload Constraints:
- Maximum file size: 10 MB default, configurable.
- MIME type validation required.
- Executable files blocked.
- File extension and MIME type both validated.
- Duplicate file handling defined by application policy.

Storage Abstraction:
- File service interface supports:
  - Upload
  - Download
  - Delete
  - Generate pre-signed URL
  - Get metadata
- Implementations:
  - Local filesystem
  - MinIO/S3-compatible storage

Tenant-Scoped Storage:
- Files stored under organization-prefixed paths.
- Example:
  /org-{organization_id}/service-points/{node_id}/attachments/{file_id}

File Metadata:
- File ID
- Organization ID
- Entity type
- Entity ID
- Original file name
- Stored path/key
- MIME type
- Size
- Uploaded by
- Created timestamp
- Purpose:
  - ATTACHMENT
  - MANUAL
  - PHOTO
  - EXPORT
  - AI_INGESTION_ARTIFACT

Manuals and Documents:
- Service points support manuals/documents.
- PDF/TXT manuals may be marked for AI ingestion.
- AI ingestion status tracked:
  - PENDING
  - PROCESSING
  - COMPLETED
  - FAILED

16. DATABASE ARCHITECTURE PRINCIPLES
--------------------------------------------------------------------------------
Primary Database:
- PostgreSQL 15+

Schema Principles:
- Every tenant table includes organization_id.
- Foreign keys enforce referential integrity.
- Soft delete used for business entities.
- Timestamps stored in UTC.
- JSONB used for custom fields and flexible metadata.
- pgvector used for AI embeddings.
- Indexes on organization_id, entity IDs, status, deadlines, and timestamps.

Global Fields:
Recommended standard fields:
- id UUID primary key
- organization_id UUID
- created_at TIMESTAMP WITH TIME ZONE
- updated_at TIMESTAMP WITH TIME ZONE
- deleted_at TIMESTAMP WITH TIME ZONE NULL
- is_active BOOLEAN
- created_by UUID
- updated_by UUID NULL

Timezone Rule:
- All persisted timestamps in UTC.
- Frontend displays timestamps in user profile timezone.
- Cron evaluation uses UTC internally.
- User-facing scheduling may convert to user timezone for display only.

Soft Delete Policy:
- Standard user actions do not hard-delete operational records.
- Soft delete preserves history and audit.
- Unique constraints must account for deleted records where necessary.

Hierarchy Support:
- Recursive CTEs for tree queries.
- Depth limit enforced at application and database level.
- Path column optional for performance.

Custom Fields:
- Organization: 2 to 3 custom fields.
- Zone: up to 5 custom fields.
- Stored as JSONB with application-level validation.

Future Inventory Slots:
- Parts table placeholder.
- Spare parts table placeholder.
- Service point parts relationship placeholder.
- Work order part usage placeholder.
- These are structural slots; full inventory is post-MVP.

17. API ARCHITECTURE
--------------------------------------------------------------------------------
API Style:
- REST API.
- Versioned base path:
  /api/v1
- JSON request/response.
- OpenAPI/Swagger documentation generated by FastAPI.

Authentication Endpoints:
- POST /auth/signup
- POST /auth/login
- POST /auth/refresh
- POST /auth/logout
- POST /auth/forgot-password
- POST /auth/reset-password
- GET /auth/me

Organization Endpoints:
- GET /organizations/me
- PATCH /organizations/me
- GET /organizations/tier
- POST /organizations/invitations
- GET /organizations/invitations
- DELETE /organizations/invitations/{id}
- POST /organizations/invitations/accept

Asset Endpoints:
- CRUD /zones
- CRUD /systems
- CRUD /sub-systems
- CRUD /service-points
- GET /service-points/{id}/history
- GET /service-points/{id}/manuals
- POST /service-points/{id}/counters/log
- POST /service-points/{id}/counters/reset
- GET /qr/resolve/{code}

Cycle Endpoints:
- CRUD /cycles
- POST /cycles/{id}/suspend
- POST /cycles/{id}/activate
- GET /cycles/{id}/evaluations
- POST /cycles/{id}/manual-trigger

Workflow/Checklist Endpoints:
- CRUD /workflows
- CRUD /checklists
- GET /workflows/search
- GET /checklists/search
- POST /ai/checklists/generate
- GET /ai/generations/{id}

Work Order Endpoints:
- GET /work-orders
- GET /work-orders/{id}
- POST /work-orders/{id}/acknowledge
- POST /work-orders/{id}/reject
- POST /work-orders/{id}/snooze
- PATCH /work-orders/{id}/items/{itemId}
- POST /work-orders/{id}/comments
- POST /work-orders/{id}/attachments

Ticket Endpoints:
- POST /tickets
- GET /tickets
- GET /tickets/{id}
- POST /tickets/{id}/claim
- POST /tickets/{id}/assign
- POST /tickets/{id}/report
- POST /tickets/{id}/feedback
- POST /tickets/{id}/accept
- POST /tickets/{id}/escalate

Notification Endpoints:
- GET /notifications
- POST /notifications/{id}/read
- POST /notifications/read-all

Reporting Endpoints:
- GET /reports/work-orders
- GET /reports/tickets
- GET /reports/assets
- POST /reports/export

File Endpoints:
- POST /files/upload
- GET /files/{id}
- GET /files/{id}/download-url
- DELETE /files/{id}

AI Assistant Endpoints:
- POST /ai/assistant/threads
- POST /ai/assistant/threads/{id}/messages
- GET /ai/assistant/threads/{id}/messages
- POST /ai/manuals/{fileId}/reprocess

Validation:
- Pydantic models validate all input.
- Pagination standard:
  - page
  - page_size
  - total
- Filtering and sorting explicitly allowed per endpoint.
- Error format standard:
  - error_code
  - message
  - details

18. BACKGROUND PROCESSING ARCHITECTURE
--------------------------------------------------------------------------------
Celery Workers:
- Handle asynchronous and long-running tasks.
- Prevent API request blocking.

Key Background Tasks:
1. Cycle Evaluation
   - Evaluate calendar cycles.
   - Evaluate counter cycles.
   - Generate work orders.
   - Detect missed cycles.

2. Work Order Snooze Expiration
   - Reactivate snoozed work orders.
   - Send notifications.

3. Invitation Expiry
   - Expire invitations older than 14 days.

4. Notification Expiry
   - Archive/expire notifications after 30 days.

5. Zone Cloning
   - Clone zones and related entities.

6. Report Export
   - Generate CSV/XLSX exports.

7. File Ingestion
   - Extract text from PDF/TXT manuals.
   - Chunk text.
   - Generate embeddings.
   - Store vectors.

8. AI Checklist Generation
   - Call LLM provider.
   - Validate structured output.
   - Store generation result.

9. AI Assistant Answer Generation
   - Retrieve relevant chunks.
   - Call LLM.
   - Store message logs.
   - Return answer or stream response.

Idempotency:
- Cycle generation must avoid duplicate work orders.
- Use Redis locks or database constraints.
- Store cycle evaluation results.

Retry Policy:
- Retries for transient external failures.
- Exponential backoff.
- Dead-letter or failed-job inspection for persistent failures.

Observability:
- Task IDs logged.
- Job status stored.
- Failure reasons stored.
- Admin can inspect failed background jobs.

19. AI SUBSYSTEM ARCHITECTURE
--------------------------------------------------------------------------------
The MVP includes two AI capabilities:

AI Phase 1:
- Automated Checklist Generation.

AI Phase 2:
- RAG Manual Assistant.

Both capabilities shall be implemented with tenant isolation, auditability,
and provider abstraction.

19.1 AI Provider Abstraction
--------------------------------------------------------------------------------
AI provider layer shall support:
- Text completion/chat models.
- Embedding models.
- Configurable base URL.
- API key management through environment secrets.
- Model name configuration.
- Timeout and retry settings.
- Local/self-hosted model support.

Provider Interface:
- generate_text(prompt, schema, options)
- generate_embedding(text)
- stream_text(prompt, options) optional

Model Configuration:
- External provider enabled/disabled.
- Local model enabled/disabled.
- Organization-level privacy mode optional.
- If external provider is used, prompts shall be sanitized.

19.2 AI Checklist Generation
--------------------------------------------------------------------------------
Purpose:
- Allow managers to generate draft checklists from natural language prompts.

User Flow:
1. Manager opens checklist creation.
2. Manager clicks AI Generate.
3. Manager enters prompt, e.g.:
   "Create a monthly inspection checklist for a 500kVA diesel generator."
4. Backend sends prompt to AI generation service.
5. LLM returns structured JSON.
6. Backend validates output.
7. UI displays draft items for review.
8. Manager edits/approves and saves checklist.

Generated Fields:
- Item description
- Suggested measurement type
- Measurement unit
- Min threshold
- Max threshold
- Estimated duration
- Risk level suggestion
- Required tools suggestion
- Required skills suggestion

Output Validation:
- LLM output must match JSON schema.
- Invalid output triggers retry or error message.
- AI output is treated as draft, not authoritative.
- Manager review required before checklist becomes active.

Processing Model:
- For short prompts, synchronous API may be acceptable.
- For reliability, Celery task recommended.
- AI generation job states:
  - PENDING
  - PROCESSING
  - COMPLETED
  - FAILED

AI Generation Logs:
- Organization ID
- User ID
- Prompt
- Model
- Provider
- Output
- Status
- Error
- Created timestamp

Privacy:
- Prompt shall not include organization ID.
- Prompt shall not include user personal data.
- Prompt may include equipment type and maintenance context.

19.3 RAG Manual Assistant
--------------------------------------------------------------------------------
Purpose:
- Provide maintenance users with an interactive assistant grounded in the
  manuals/documents attached to a specific service point.

User Flow:
1. User opens service point, work order, or workflow screen.
2. User opens AI Manual Assistant.
3. User asks a question, e.g.:
   "What is the torque specification for the main bearing?"
4. Backend retrieves relevant manual chunks for that node.
5. LLM answers using only retrieved context.
6. Answer includes citations/reference to source file and page where possible.

RAG Pipeline:
1. Manual/document uploaded to service point.
2. File marked eligible for AI ingestion.
3. Celery task extracts text.
4. Text is split into chunks.
5. Chunks are embedded.
6. Embeddings stored in pgvector.
7. Metadata stored:
   - organization_id
   - service_point_id
   - file_id
   - page number
   - chunk index
   - section heading if available
   - token count
   - created timestamp

Retrieval Rules:
- Retrieval must filter by organization_id.
- Retrieval must filter by permitted service point.
- Retrieval should filter by file IDs if user selects specific manuals.
- Top-k retrieval used.
- Similarity threshold may be applied.
- If no relevant context is found, assistant shall say it cannot find the
  answer in the attached manuals.

Answer Rules:
- Answer grounded in retrieved chunks.
- No cross-organization context.
- No hallucinated specifications if context absent.
- Citations included where possible.
- Assistant responses may be logged for debugging and quality review.

Assistant Threads:
- Optional thread model:
  - Thread belongs to user and service point.
  - Messages stored with role:
    - user
    - assistant
- Context limited to recent messages and retrieved document chunks.
- Long-term memory not required for MVP.

AI Assistant Permissions:
- User must have permission to view the service point and manuals.
- Maintenance, Manager, and permitted roles may use assistant.
- Operator access may be allowed if manuals/node access is permitted.

AI Rate Limits:
- AI endpoints shall have stricter rate limits than normal API.
- Per-user and per-organization limits recommended.
- Queue or throttle long-running assistant requests.

20. AUDIT LOGGING AND COMPLIANCE ARCHITECTURE
--------------------------------------------------------------------------------
Audit logs shall be immutable or append-only.

Audited Events:
- User login/logout
- Password reset
- Role changes
- User deactivation
- Organization creation/update
- Invitation create/accept/expire
- Zone/system/service point create/update/decommission
- Cycle create/update/suspend/trigger
- Work order generate/acknowledge/reject/snooze/complete
- Ticket create/claim/report/feedback/escalate/close
- Safety flag changes
- Counter reset/log
- File upload/delete
- AI generation request
- AI assistant request optional
- Manual override by system administrator

Audit Log Fields:
- Audit ID
- Organization ID
- Actor user ID
- Actor role
- Action
- Entity type
- Entity ID
- Previous state JSON
- New state JSON
- IP address
- User agent
- Timestamp UTC

Implementation:
- Domain service emits audit events.
- Audit events written transactionally where practical.
- Background worker may batch persist non-critical logs.
- Sys admin actions always logged.

21. SECURITY ARCHITECTURE
--------------------------------------------------------------------------------
Transport Security:
- HTTPS enforced.
- SSL termination at reverse proxy/WAF.
- HSTS recommended.

Authentication Security:
- Short-lived JWT access tokens.
- HttpOnly refresh tokens.
- Refresh token rotation.
- Secure cookie flags.
- Password hashing using strong algorithm, e.g. Argon2 or bcrypt.
- Password reset tokens single-use and time-limited.
- Email verification tokens single-use and time-limited.

Authorization:
- RBAC enforced at endpoint and object level.
- Deactivated users blocked from new actions.
- Overdue organizations blocked from new repair tickets.
- Tier limits enforced for service point creation.

Rate Limiting:
- Redis-based rate limiting.
- General API limit per IP/user.
- Stricter limits for:
  - Login
  - Password reset
  - Invitation creation
  - File upload
  - AI checklist generation
  - AI assistant

File Security:
- MIME validation.
- Size limit.
- Tenant-scoped storage.
- Pre-signed URLs with short expiry.
- No direct public bucket access.

AI Security:
- No cross-tenant retrieval.
- Prompt sanitization.
- No sensitive personal data in prompts unless necessary.
- Optional local model mode.
- AI outputs validated for structured generation.
- AI usage logs retained.

Input Validation:
- Pydantic validation.
- SQL injection prevented by ORM/parameterized queries.
- XSS mitigated by React escaping and CSP.
- CSRF protection for cookie-based refresh flows where applicable.

Secrets:
- Secrets stored in environment variables or secret manager.
- No secrets in code repository.
- Separate secrets for dev/staging/prod.

22. FRONTEND ARCHITECTURE
--------------------------------------------------------------------------------
Frontend Application:
- React SPA.
- TypeScript.
- Vite build.
- Responsive layout.
- RTL/LTR support.
- Bi-directional text entry.

State Management:
- React Query for server state.
- Local UI state via React Context or lightweight store.
- Form state via controlled forms or form library.

Routing:
- Public routes:
  - Login
  - Signup
  - Verify email
  - Forgot password
  - Reset password
- Authenticated routes:
  - Dashboard
  - Assets
  - Zones
  - Systems
  - Service points
  - Cycles
  - Workflows
  - Checklists
  - Work orders
  - Tickets
  - Reports
  - Notifications
  - Settings
  - AI tools

RTL/LTR Support:
- Tailwind logical properties.
- Direction switcher or user/org locale setting.
- Layout mirrors correctly for RTL.
- Inputs support bi-directional text where appropriate.

QR Scanning:
- Browser camera access.
- HTML5 scanner.
- Resolve scanned code through API.
- Display node profile/history/manuals according to role.

Notification UI:
- Bell icon.
- Unread badge.
- Dropdown/list.
- Mark as read.
- Deep-link navigation.

AI Checklist Generation UI:
- Prompt input.
- Generate button.
- Loading state.
- Draft preview table.
- Editable generated items.
- Approve/save button.
- Error handling for invalid AI output.

AI Manual Assistant UI:
- Chat panel.
- Node/manual context indicator.
- Streaming answer support optional.
- Citation list.
- Source file/page reference.
- Retry button.
- Clear thread button.
- Permission-aware availability.

Offline Support:
- Not included in MVP.
- Application requires active internet connection.
- Explicitly excluded to avoid scope creep.

23. REPORTING EXPORT ARCHITECTURE
--------------------------------------------------------------------------------
Export Request Flow:
1. User selects report filters.
2. User requests export.
3. API creates export job.
4. Celery worker generates file.
5. File stored in tenant-scoped storage.
6. Notification sent when export ready.
7. Short-lived download URL provided.

Export Formats:
- CSV required.
- XLSX optional.

Export Security:
- Exports respect tenant isolation.
- Exports stored under organization path.
- Download URLs expire.

24. DEPLOYMENT TOPOLOGY
--------------------------------------------------------------------------------
Internet Traffic:
[Internet]
   |
[Cloudflare / WAF]
   |
[Nginx Reverse Proxy]
   |
   ├── /api/* -> FastAPI application
   ├── /static/* -> React SPA static assets
   └── /storage/* -> MinIO/S3 or pre-signed redirect
   └── /mcp/* -> [MCP Server] (authenticated, rate-limited)

Application Services:
- nginx
- api
- worker
- beat
- db
- redis
- minio

Docker Compose Services:
1. nginx
   - Reverse proxy.
   - Static file serving.
   - TLS termination in production if not handled upstream.
   - mcp: MCP Server (External AI Operability)

2. api
   - FastAPI app.
   - Gunicorn/Uvicorn workers.
   - OpenAPI docs.
   - Health endpoints.

3. worker
   - Celery workers.
   - Handles AI, cycles, exports, ingestion, notifications.

4. beat
   - Celery Beat scheduler.
   - Triggers periodic jobs.

5. db
   - PostgreSQL 15+.
   - pgvector installed.
   - Persistent volume.

6. redis
   - Broker/cache/rate limiter/delayed queue.
   - Persistent volume recommended.

7. minio
   - S3-compatible object storage.
   - Persistent volume.
   - Tenant-prefixed buckets/paths.

Optional Supporting Services:
- Flower or admin queue dashboard for Celery monitoring.
- Prometheus/Grafana optional.
- Log aggregator optional.

25. MCP SERVER — EXTERNAL AI OPERABILITY
--------------------------------------------------------------------------------
25.1 Purpose
------------
The system shall expose a Model Context Protocol (MCP) server that publishes
the full CMMS capability surface (tools, resources, and prompts) so that an
external AI agent can query, operate, and automate the system autonomously.

The MCP server is a read/write bridge, not a replacement for the REST API.
It wraps the same domain services the REST API uses, inheriting every
multi-tenancy, RBAC, and safety rule already defined.

25.2 Protocol & Transport
-------------------------
- Protocol: MCP (Model Context Protocol), JSON-RPC 2.0 based.
- Transport: Stdio (for local/sidecar agents) and Streamable HTTP / SSE
  (for remote agents and cloud-hosted AI orchestrators).
- The server shall support both transports behind a single binary/service.
- Version pinning: the server shall advertise supported MCP spec versions
  and reject unsupported clients.

25.3 Deployment Position
------------------------
[External AI Agent / Orchestrator]
        |
        | MCP (Stdio or HTTP/SSE)
        v
[MCP Server]  ←── scoped API key / OAuth token
        |
        | Internal service calls (same code path as REST)
        v
[FastAPI Domain Services]
        |
   ┌────┴────┐
[PostgreSQL] [Redis] [MinIO] [Celery]

The MCP server runs as an independent Docker service ("mcp") in the
compose stack. It does NOT expose HTTP endpoints to the public internet
by default; it sits behind Nginx or a private network, reachable only by
authorized AI orchestrators.

25.4 Authentication & Tenant Scoping
------------------------------------
- Every MCP session must authenticate before any tool/resource call.
- Accepted credential types:
  a) Short-lived JWT (same 15-min access + refresh model as REST).
  b) Scoped API key bound to one organization_id and one logical role.
- The MCP server extracts organization_id and role from the credential
  and injects them into every downstream domain call.
- Cross-tenant access is impossible by construction: the same RLS and
  org_id filters used by the REST API apply.

25.5 RBAC Mapping for MCP Agents
--------------------------------
An MCP session operates under exactly one of the existing roles:
  MANAGER, REPORTER, OPERATOR, MAINTENANCE.
There is no separate "MCP role". The external AI inherits whatever
permissions that role already has.

Recommended practice:
- Autonomous planning agents   → MANAGER scope (full read + write).
- Diagnostic / reporting agents → REPORTER scope (read + manual trigger).
- Field-assist agents           → OPERATOR scope (log counters, tickets).
- Execution agents              → MAINTENANCE scope (update work orders).

The SYS_ADMIN role shall NOT be exposed through MCP under any
circumstance.

25.6 Exposed MCP Resources (Read Surface)
------------------------------------------
Resources are read-only data the AI can retrieve.

  cmms://assets/zones
  cmms://assets/systems
  cmms://assets/service-points/{id}
  cmms://assets/service-points/{id}/history
  cmms://assets/service-points/{id}/manuals
  cmms://cycles/{id}
  cmms://workflows/{id}
  cmms://checklists/{id}
  cmms://work-orders
  cmms://work-orders/{id}
  cmms://tickets
  cmms://tickets/{id}
  cmms://reports/kpis
  cmms://notifications

Each resource honours the caller's role and organization scope.

25.7 Exposed MCP Tools (Write / Action Surface)
-------------------------------------------------
Tools are actions the AI can invoke. Grouped by domain:

Asset Management (MANAGER only):
  create_zone, update_zone, clone_zone, decommission_zone
  create_system, update_system
  create_service_point, update_service_point
  generate_qr, decommission_service_point

Cycle & Schedule Management (MANAGER only):
  create_cycle, update_cycle, suspend_cycle, activate_cycle
  assign_workflow_to_cycle, assign_checklist_to_cycle
  set_cycle_flag (HOT_INSPECT / PAUSE / STOP_UNTIL_COMPLETE)

Counter Operations (OPERATOR, MANAGER):
  log_operating_hours, log_operation_count
  reset_counter (scope: node | node+children)

Work Order Operations (MAINTENANCE, MANAGER):
  acknowledge_work_order
  reject_work_order (requires reason)
  snooze_work_order (requires duration + reason)
  update_work_order_item_status
  record_measurement
  submit_work_order_signature
  add_work_order_comment

Ticket Operations (OPERATOR, MANAGER, MAINTENANCE):
  create_repair_ticket (blocked if org is overdue)
  submit_ticket_report
  submit_ticket_feedback
  accept_ticket
  escalate_ticket

Workflow / Checklist Authoring (MANAGER only):
  create_workflow, create_checklist
  add_workflow_item, add_checklist_item
  ai_generate_checklist  (wraps the internal Phase-1 AI)

AI Assistant (any authenticated role):
  ask_manual_assistant  (wraps the internal Phase-2 RAG)

Reporting (MANAGER, REPORTER):
  get_kpi_dashboard, export_report

25.8 Exposed MCP Prompts (Guided Templates)
--------------------------------------------
Pre-built prompt templates the external AI can load:

  prompt://cycle-analysis
    → "Analyse cycle {id} and suggest optimisations."
  prompt://overdue-triage
    → "List overdue work orders and propose a prioritised action plan."
  prompt://root-cause
    → "Given ticket {id} and its feedback history, suggest root causes."
  prompt://zone-onboarding
    → "Guide me through setting up a new zone with systems and nodes."

25.9 Safety Guardrails for Autonomous Operation
------------------------------------------------
Because the MCP server grants an external AI write access to a
maintenance-safety-critical system, the following guardrails are
MANDATORY:

a) Confirmation Gates
   The following tools require an explicit human confirmation token
   before execution, even in autonomous mode:
     - set_cycle_flag with STOP_UNTIL_COMPLETE
     - decommission_zone / decommission_service_point
     - clone_zone (large side-effect)
     - create_repair_ticket with priority CRITICAL
   The MCP tool returns a pending_confirmation state and a confirmation
   URL/token. The AI must present this to a human operator.

b) Dry-Run Mode
   Every write tool accepts an optional "dry_run": true parameter.
   When set, the server validates inputs, computes side-effects, and
   returns the expected result without persisting anything.

c) Rate Limiting
   MCP calls inherit the same Redis-based rate limiter as REST.
   Additional per-tool limits:
     - Write tools: max 30 calls / minute per session.
     - AI-assist tools: max 10 calls / minute per session.

d) Operation Ceiling
   A single MCP session may not create more than 50 work orders or
   50 tickets per hour. Exceeding the ceiling returns a quota error.

e) No Safety-Flag Override
   An MCP agent cannot clear or downgrade a STOP_UNTIL_COMPLETE flag
   that was set by a human user. It can only escalate.

f) Rollback Window
   All MCP write operations are wrapped in database transactions.
   A batch_rollback tool allows the AI to undo the last N operations
   within a configurable window (default 5 minutes), provided no
   human has acted on those records in the interim.

25.10 Audit & Traceability
---------------------------
- Every MCP tool call is logged in the existing audit_logs table with:
    actor_type = "MCP_AGENT"
    actor_id   = MCP session / API key identifier
    tool_name  = <tool called>
    input_hash = SHA-256 of the input payload
    result     = SUCCESS | FAILED | PENDING_CONFIRMATION
- MCP sessions are distinguishable from REST sessions in all audit
  queries and dashboards.
- An organization manager can view a filtered "AI Activity Log"
  showing every MCP-driven change.

25.11 MCP Server Technology
----------------------------
- Language: Python 3.11+ (same as backend).
- Framework: "mcp" Python SDK (official Model Context Protocol SDK)
  or equivalent maintained library.
- Shares the same SQLAlchemy models, Pydantic schemas, and domain
  service layer as the FastAPI application to guarantee behavioural
  parity.
- Packaged as a separate Docker service ("mcp") in docker-compose.
- Health endpoint: /health on the MCP HTTP transport.
- Configuration via environment variables:
    MCP_TRANSPORT=stdio|http
    MCP_HTTP_PORT=8100
    MCP_ALLOWED_ORIGINS=<comma-separated list>
    MCP_MAX_BATCH_SIZE=50
    MCP_CONFIRMATION_REQUIRED=true|false
    MCP_DRY_RUN_DEFAULT=false

25.12 Updated Docker Compose Service
--------------------------------------
Add to the existing compose stack:

  mcp:
    build: ./services/mcp
    depends_on: [api, db, redis]
    environment:
      - DATABASE_URL=postgresql+asyncpg://...
      - REDIS_URL=redis://redis:6379/0
      - MCP_TRANSPORT=http
      - MCP_HTTP_PORT=8100
      - JWT_SECRET=${JWT_SECRET}
    ports:
      - "8100:8100"   # expose only on private network by default
    restart: unless-stopped

25.13 Updated Deployment Topology Diagram
-------------------------------------------
[Internet]
    |
[Cloudflare / WAF]
    |
[Nginx Reverse Proxy]
├── /api/*    → [FastAPI]
├── /static/* → [React SPA]
├── /storage/*→ [MinIO / S3]
└── /mcp/*    → [MCP Server]  (restricted access)

[External AI Agent]
    |
    | MCP over HTTP/SSE (authenticated)
    v
[MCP Server :8100]
    |
    | Shared domain service layer
    v
[FastAPI domain services] → [PostgreSQL] / [Redis] / [MinIO] / [Celery]



26. OBSERVABILITY AND OPERATIONS
--------------------------------------------------------------------------------
Health Checks:
- /health/live
- /health/ready
- Database connectivity check.
- Redis connectivity check.
- Storage connectivity check.

Logging:
- Structured JSON logs.
- Request ID correlation.
- User ID and organization ID where available.
- Background job logs.
- AI provider logs with sensitive data redacted.

Metrics:
- API request latency.
- Error rates.
- Background queue length.
- Cycle evaluation success/failure.
- Work order generation count.
- Ticket escalation count.
- AI generation latency.
- RAG retrieval latency.
- File upload failures.

Error Handling:
- Central exception handler.
- Standard error response.
- Do not leak stack traces to client.
- Log full details server-side.

Backup:
- PostgreSQL scheduled backups.
- Object storage backups or replication.
- Restoration procedure documented.

Configuration:
- Environment-based config.
- Separate dev/staging/prod.
- Feature flags for AI provider mode.

27. TESTING STRATEGY
--------------------------------------------------------------------------------
Backend Tests:
- Unit tests for domain logic.
- API integration tests.
- RBAC tests.
- Tenant isolation tests.
- Cycle trigger tests.
- Work order lifecycle tests.
- Ticket loop/escalation tests.
- File validation tests.
- AI output validation tests using mocked providers.

Frontend Tests:
- Component tests.
- Form validation tests.
- RTL/LTR rendering tests.
- Role-based UI visibility tests.

End-to-End Tests:
- Signup/login/password reset.
- Organization setup.
- Asset creation.
- Cycle creation and work order generation.
- Checklist creation with AI draft.
- Ticket lifecycle.
- Notification center.
- QR scan flow.

AI Tests:
- Mock LLM responses.
- Invalid JSON handling.
- RAG retrieval isolation.
- No cross-organization document retrieval.
- Assistant fallback when no context found.

CI/CD:
- GitHub Actions pipeline.
- Lint.
- Test.
- Build.
- Database migration check.
- Docker image build.
- Deploy to staging.
- Optional production deployment with manual approval.

28. DATA MODEL SUMMARY
--------------------------------------------------------------------------------
Major entity groups:

Identity and Tenancy:
- organizations
- organization_custom_fields
- users
- user_organization_memberships
- roles
- auth_refresh_tokens
- email_verification_tokens
- password_reset_tokens
- invitations
- subscription_tiers
- payment_states

Assets:
- zones
- zone_custom_fields
- systems
- system_zone_links
- sub_systems
- service_points
- asset_qr_codes
- counters
- counter_logs
- spare_parts_placeholder
- service_point_parts_placeholder

Maintenance Definitions:
- cycles
- cycle_triggers
- cycle_evaluations
- workflows
- checklist_templates
- workflow_items
- checklist_items
- safety_flags

Execution:
- work_orders
- work_order_items
- work_order_item_measurements
- work_order_comments
- work_order_attachments
- work_order_signatures
- snooze_records
- rejection_records

Ticketing:
- tickets
- ticket_reports
- ticket_feedbacks
- ticket_assignments
- ticket_events

Notifications and Reporting:
- notifications
- dashboard_metrics
- report_exports
- audit_logs

Files and AI:
- files
- document_ingestion_jobs
- document_chunks
- ai_generation_jobs
- ai_assistant_threads
- ai_assistant_messages
- ai_usage_logs

Vector Data:
- document_chunks.embedding using pgvector

29. MVP SCOPE BOUNDARIES
--------------------------------------------------------------------------------
Included in MVP:
- Full core CMMS flows.
- Multi-tenant isolation.
- JWT auth and password recovery.
- In-app notifications only.
- Transactional email for auth only.
- Asset hierarchy with soft delete.
- QR generation/print/scan.
- Cycle engine with suspension and missed-cycle handling.
- Work orders with snooze/reject/acknowledge.
- Repair tickets with priority, pool assignment, 3 loops, escalation.
- File upload constraints.
- Audit logging.
- API rate limiting.
- OpenAPI documentation.
- UTC storage and user-timezone display.
- AI checklist generation.
- AI RAG manual assistant.

Explicitly excluded from MVP:
- Offline mode.
- IoT/sensor integration.
- Vision AI ticketing.
- Vision-based spare part identification.
- Full inventory management.
- Automated part reordering.
- SSO/OAuth.
- MFA/2FA.
- Sub-organizations.
- Seasonal cycles.
- Conditional workflow triggers.
- Parallel workflow branches.
- Workflow versioning.
- Automatic pass/fail from measurement thresholds.
- Full UI multi-language localization.
- Email/SMS operational notifications.

30. ARCHITECTURAL DECISIONS AND RATIONALE
--------------------------------------------------------------------------------
Decision: FastAPI + Celery + PostgreSQL + Redis
Reason: Supports async API, background jobs, scheduled tasks, and scalable
MVP architecture.

Decision: PostgreSQL with pgvector
Reason: Avoids adding a separate vector database for MVP RAG while keeping
tenant isolation simple.

Decision: MinIO/S3 abstraction
Reason: Supports local development and production object storage without
changing application code.

Decision: React Query for server state
Reason: Simplifies caching, polling, invalidation, and notification updates.

Decision: Soft delete globally
Reason: Maintenance systems require historical preservation and auditability.

Decision: Snapshot-based work orders
Reason: Parent cycle/template changes must not retroactively alter existing
execution records.

Decision: In-app notifications only
Reason: Reduces MVP scope while still supporting operational awareness.

Decision: AI as assistant, not authority
Reason: AI outputs must be reviewed by humans for safety, compliance, and
maintenance correctness.

Decision: Provider-abstracted AI
Reason: Allows external LLMs for convenience and local models for privacy.

31. END OF ARCHITECTURE DOCUMENT
--------------------------------------------------------------------------------
This architecture shall support the full MVP technical requirements, including
multi-tenancy, strict security, asset hierarchy, cycle automation, work orders,
repair ticketing, notifications, reporting, QR access, file storage, audit
logging, timezone normalization, soft deletion, OpenAPI documentation, and
AI Phase 1 / Phase 2 capabilities.
