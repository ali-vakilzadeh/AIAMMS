# CMMS SaaS Server API Architecture Reference

This document provides a comprehensive reference of all API commands, syntaxes, response formats, and architectural components organized by development chunk and module.

---

## Table of Contents

1. [Modules Overview](#modules-overview)
2. [API Commands & Functions](#api-commands--functions)
3. [Module Exports](#module-exports)
4. [Event Catalog](#event-catalog)
5. [Database Tables](#database-tables)
6. [State Machines](#state-machines)

---

## Modules Overview

| Chunk | Module | Description |
|-------|--------|-------------|
| 1 | core | Core Kernel & Module System |
| 1 | shared | Core Kernel & Module System |
| 2 | db | Infrastructure Layer - DB, Cache, Storage, Email |
| 2 | cache | Infrastructure Layer - DB, Cache, Storage, Email |
| 2 | storage | Infrastructure Layer - DB, Cache, Storage, Email |
| 2 | email | Infrastructure Layer - DB, Cache, Storage, Email |
| 3 | api | API Surface & Worker Engine |
| 3 | worker | API Surface & Worker Engine |
| 10 | tickets | Tickets - Repair Ticketing & Files |
| 10 | files | Tickets - Repair Ticketing & Files |
| 11 | ai | AI Module - Checklist Generation & RAG Assistant |
| 11 | files | AI Module - Checklist Generation & RAG Assistant |

---

## API Commands & Functions

### Chunk 1 - Core Kernel & Module System

#### `ModuleBase.configure`

**Location:** `/src/server/core/module_base.py`

**Syntax:** `async configure(settings: Any) -> None`

**Inputs:** `settings`: Pydantic Settings object from core.module_settings(name)

**Response Format:** None

**Behavior/Conditions:** Called during boot before initialize(); Store settings for later use

---

#### `ModuleBase.initialize`

**Location:** `/src/server/core/module_base.py`

**Syntax:** `async initialize(ctx: ModuleContext) -> None`

**Inputs:** `ctx`: ModuleContext with platform-level context

**Response Format:** None

**Behavior/Conditions:** Called after configure(); Create DB tables, pools, caches

---

#### `ModuleBase.start`

**Location:** `/src/server/core/module_base.py`

**Syntax:** `async start() -> None`

**Response Format:** None

**Behavior/Conditions:** Called after initialize(); Start background loops, register tasks

---

#### `ModuleBase.stop`

**Location:** `/src/server/core/module_base.py`

**Syntax:** `async stop() -> None`

**Response Format:** None

**Behavior/Conditions:** Called during shutdown; Drain in-flight work, close connections

---

#### `ModuleBase.health`

**Location:** `/src/server/core/module_base.py`

**Syntax:** `async health() -> dict`

**Response Format:** {'status': 'HealthStatus', 'checks': 'list of check results', 'ts': 'datetime'}

**Behavior/Conditions:** Called periodically by supervisor; Must return within 2s timeout

---

#### `register_service`

**Location:** `/src/server/core/registry.py`

**Syntax:** `register_service(name: str, port: Any, interface: type) -> None`

**Inputs:** `name`: Service name e.g. 'db'; `port`: Implementation instance; `interface`: Protocol/type

**Response Format:** None

**Behavior/Conditions:** Raises DuplicateServiceError on duplicate name

---

#### `get_service`

**Location:** `/src/server/core/registry.py`

**Syntax:** `get_service(name: str, interface: type) -> Any`

**Inputs:** `name`: Service name; `interface`: Expected Protocol

**Response Format:** The registered port instance

**Behavior/Conditions:** Raises ServiceNotRegisteredError if not found; Raises InterfaceMismatchError on type mismatch

---

#### `subscribe`

**Location:** `/src/server/core/event_bus.py`

**Syntax:** `subscribe(event: str, handler: Callable, post_commit: bool = False) -> None`

**Inputs:** `event`: Event name or '*' for wildcard; `handler`: Async callable(payload); `post_commit`: Defer until DB commit

**Response Format:** None

**Behavior/Conditions:** Raises ValueError on duplicate (event, handler) pair

---

#### `publish`

**Location:** `/src/server/core/event_bus.py`

**Syntax:** `async publish(event: str, payload: dict, post_commit: bool = False) -> None`

**Inputs:** `event`: Dot-delimited name e.g. 'cycle.due'; `payload`: JSON-serializable dict; `post_commit`: Queue for post-commit delivery

**Response Format:** None

**Behavior/Conditions:** Subscriber failures isolated - one failing listener never breaks others; Wildcard '*' subscribers receive ALL events

---

#### `flush_post_commit`

**Location:** `/src/server/core/event_bus.py`

**Syntax:** `async flush_post_commit() -> None`

**Response Format:** None

**Behavior/Conditions:** Called by DB module after successful transaction commit

---

#### `load_settings`

**Location:** `/src/server/core/settings.py`

**Syntax:** `load_settings() -> SettingsBundle`

**Response Format:** SettingsBundle with per-module validated settings

**Behavior/Conditions:** Fails boot with field-level error list on invalid config; Secrets never logged

---

#### `module_settings`

**Location:** `/src/server/core/settings.py`

**Syntax:** `module_settings(name: str) -> BaseModel | None`

**Inputs:** `name`: Module name e.g. 'db', 'cache'

**Response Format:** Module's pydantic Settings instance or None

**Behavior/Conditions:** Used by modules during configure()

---

#### `validate_dependency_graph`

**Location:** `/src/server/core/dependency.py`

**Syntax:** `validate_dependency_graph(modules: list[ModuleMeta]) -> None`

**Inputs:** `modules`: Discovered metadata list

**Response Format:** None

**Behavior/Conditions:** Raises UnknownDependencyError if dependency references unknown module; Raises DependencyCycleError(cycle_path) if cycle detected

---

#### `topological_sort`

**Location:** `/src/server/core/dependency.py`

**Syntax:** `topological_sort(modules: list[ModuleMeta]) -> list[str]`

**Inputs:** `modules`: Validated metadata list

**Response Format:** List of module names in start order

**Behavior/Conditions:** Uses Kahn's algorithm; Alphabetical tie-break for determinism

---

#### `discover_modules`

**Location:** `/src/server/core/discovery.py`

**Syntax:** `discover_modules(package_root: str = 'modules') -> list[ModuleMeta]`

**Inputs:** `package_root`: Python package path to scan

**Response Format:** List of ModuleMeta for each discovered module

**Behavior/Conditions:** Raises DuplicateModuleError if two modules declare same name; Returns empty list if package doesn't exist yet

---

#### `boot`

**Location:** `/src/server/core/boot.py`

**Syntax:** `boot(profile: str) -> Application`

**Inputs:** `profile`: api | worker | beat | mcp | all-in-one

**Response Format:** Application{registry, event_bus, settings, started_modules}

**Behavior/Conditions:** Logs each module name+version on boot; Shutdown already-started modules on failure

---

#### `shutdown`

**Location:** `/src/server/core/boot.py`

**Syntax:** `shutdown(app: Application) -> None`

**Inputs:** `app`: Booted application

**Response Format:** None

**Behavior/Conditions:** Stops modules in reverse topological order; Each module drains in-flight work

---

#### `poll`

**Location:** `/src/server/core/health.py`

**Syntax:** `async poll(timeout_s: float = 2.0) -> dict[str, HealthReport]`

**Inputs:** `timeout_s`: Per-module timeout in seconds

**Response Format:** Map of module name -> HealthReport

**Behavior/Conditions:** Calls every module's health() concurrently; Timed-out modules reported as UNAVAILABLE

---

#### `run`

**Location:** `/src/server/core/supervisor.py`

**Syntax:** `async run(interval_s: int = 30) -> None`

**Inputs:** `interval_s`: Poll period in seconds

**Response Format:** None

**Behavior/Conditions:** Background loop until stop() called; Emits module.health_changed events on transitions

---

#### `_propagate_degradation`

**Location:** `/src/server/core/supervisor.py`

**Syntax:** `async _propagate_degradation(failed_module: str) -> None`

**Inputs:** `failed_module`: Name of UNAVAILABLE module

**Response Format:** None

**Behavior/Conditions:** Marks dependent modules as DEGRADED if hard dep is UNAVAILABLE

---

#### `utcnow`

**Location:** `/src/server/core/utils.py`

**Syntax:** `utcnow() -> datetime`

**Response Format:** TZ-aware UTC datetime

**Behavior/Conditions:** ONLY clock source - never use datetime.now() directly

---

#### `new_id`

**Location:** `/src/server/core/utils.py`

**Syntax:** `new_id() -> UUID`

**Response Format:** UUID v4

**Behavior/Conditions:** Standard ID generator for all business records

---

#### `new_request_id`

**Location:** `/src/server/core/utils.py`

**Syntax:** `new_request_id() -> str`

**Response Format:** 16-char hex string

**Behavior/Conditions:** Request correlation for distributed tracing

---

#### `setup_structured_logging`

**Location:** `/src/server/core/logger.py`

**Syntax:** `setup_structured_logging(level: int = INFO, include_locals: bool = False) -> None`

**Inputs:** `level`: Logging level; `include_locals`: Include local vars in errors

**Response Format:** None

**Behavior/Conditions:** Call once at startup; JSON output with ts, level, module, message, request_id

---

#### `get_logger`

**Location:** `/src/server/core/logger.py`

**Syntax:** `get_logger(name: str) -> ModuleLoggerAdapter`

**Inputs:** `name`: Module name e.g. 'core', 'db'

**Response Format:** Logger with module field set

**Behavior/Conditions:** Use for all module logging

---

#### `feature_enabled`

**Location:** `/src/server/core/feature_flags.py`

**Syntax:** `feature_enabled(flag: str) -> bool`

**Inputs:** `flag`: Flag name e.g. 'MCP_SERVER'

**Response Format:** True if CMMS_FEATURE_<FLAG> is truthy

**Behavior/Conditions:** Truthy values: 1, true, yes, on, enabled (case-insensitive); Default false if not set

---

### Chunk 2 - Infrastructure Layer - DB, Cache, Storage, Email

#### `build_engine`

**Location:** `/src/server/modules/db/service.py`

**Syntax:** `build_engine() -> AsyncEngine`

**Response Format:** SQLAlchemy AsyncEngine

**Behavior/Conditions:** Creates async engine from CMMS_DB__URL; Configures POOL_SIZE, MAX_OVERFLOW, POOL_TIMEOUT; Called once at initialize()

---

#### `session_factory`

**Location:** `/src/server/modules/db/service.py`

**Syntax:** `session_factory() -> async_sessionmaker[AsyncSession]`

**Response Format:** Session factory

**Behavior/Conditions:** Raw platform-level sessions for auth/platform tables before org context exists

---

#### `org_scoped_session`

**Location:** `/src/server/modules/db/service.py`

**Syntax:** `org_scoped_session(org_id: UUID) -> AsyncContextManager[AsyncSession]`

**Inputs:** `org_id`: Tenant organization ID

**Response Format:** Async context manager yielding session

**Behavior/Conditions:** Executes SET LOCAL app.organization_id = :org for PostgreSQL RLS; All domain modules MUST use this; Raises ValueError if org_id missing

---

#### `ensure_extensions`

**Location:** `/src/server/modules/db/service.py`

**Syntax:** `async ensure_extensions() -> None`

**Response Format:** None

**Behavior/Conditions:** Creates vector, pgcrypto, citext extensions

---

#### `run_migrations`

**Location:** `/src/server/modules/db/service.py`

**Syntax:** `async run_migrations(revision: str = 'head') -> None`

**Inputs:** `revision`: Alembic target revision

**Response Format:** None

**Behavior/Conditions:** Programmatic alembic upgrade; Migrations live in migrations/ stamped per owning module

---

#### `transaction`

**Location:** `/src/server/modules/db/service.py`

**Syntax:** `transaction(session: AsyncSession) -> AsyncContextManager[None]`

**Inputs:** `session`: Active session

**Response Format:** Context manager

**Behavior/Conditions:** Commit on success, rollback on exception, always close; Standardizes unit-of-work

---

#### `register_models`

**Location:** `/src/server/modules/db/service.py`

**Syntax:** `register_models(module_name: str, base: DeclarativeBase) -> None`

**Inputs:** `module_name`: Owning module name; `base`: Module's model classes

**Response Format:** None

**Behavior/Conditions:** Collect models for migration autogeneration; Enforce every tenant table has organization_id column

---

#### `health_check`

**Location:** `/src/server/modules/db/service.py`

**Syntax:** `async health_check() -> HealthReport`

**Response Format:** HealthReport

**Behavior/Conditions:** SELECT 1 probe; Report pool checkedout/size saturation; DEGRADED >80%, UNAVAILABLE on connection failure

---

#### `connect`

**Location:** `/src/server/modules/cache/service.py`

**Syntax:** `async connect() -> Redis`

**Response Format:** Async Redis client

**Behavior/Conditions:** Connect using CMMS_CACHE__URL with retry; Connection pool configured

---

#### `allow`

**Location:** `/src/server/modules/cache/service.py`

**Syntax:** `async allow(key: str, limit: int, window_s: int) -> RateDecision`

**Inputs:** `key`: e.g. 'rl:user:{id}:ai'; `limit`: Max calls; `window_s`: Window seconds

**Response Format:** RateDecision{allowed, remaining, reset_at}

**Behavior/Conditions:** Sliding-window rate limit using sorted set; Consumed by API middleware, AI and MCP limits

---

#### `lock`

**Location:** `/src/server/modules/cache/service.py`

**Syntax:** `lock(name: str, ttl_s: int, wait_ms: int = 0) -> AsyncContextManager[bool]`

**Inputs:** `name`: Lock name; `ttl_s`: Auto-release TTL; `wait_ms`: Optional wait time

**Response Format:** Context manager with acquired bool

**Behavior/Conditions:** SET NX PX with Lua compare-and-delete for safe release; Used for cycle idempotency and MCP batch ops

---

#### `delay_schedule`

**Location:** `/src/server/modules/cache/service.py`

**Syntax:** `async delay_schedule(task_name: str, payload: dict, run_at: datetime) -> str`

**Inputs:** `task_name`: Worker task; `payload`: Args; `run_at`: UTC datetime

**Response Format:** job_id

**Behavior/Conditions:** ZADD score=timestamp; Powers snooze expiration and scheduled reminders

---

#### `delay_due`

**Location:** `/src/server/modules/cache/service.py`

**Syntax:** `async delay_due(now: datetime) -> list[DelayedJob]`

**Inputs:** `now`: UTC datetime

**Response Format:** List of DelayedJob{job_id, task_name, payload}

**Behavior/Conditions:** Atomically pop all entries with score <= now via ZPOPMIN; Called by beat task which dispatches to WORKER

---

#### `kv_get/kv_set/kv_delete`

**Location:** `/src/server/modules/cache/service.py`

**Syntax:** `async kv_get(key) -> str|None; kv_set(key, value, ttl_s); kv_delete(key)`

**Inputs:** `key`: String key; `value`: String value; `ttl_s`: Optional expiry

**Response Format:** Stored value or None

**Behavior/Conditions:** Short-lived cache storage; Used for token revocation, rate limit state

---

#### `broker_url`

**Location:** `/src/server/modules/cache/service.py`

**Syntax:** `broker_url() -> str`

**Response Format:** Redis URL string

**Behavior/Conditions:** Returns Redis URL for Celery broker configuration

---

#### `health_check`

**Location:** `/src/server/modules/cache/service.py`

**Syntax:** `async health_check() -> HealthReport`

**Response Format:** HealthReport

**Behavior/Conditions:** PING probe + latency measurement + memory usage; DEGRADED if latency >100ms

---

#### `backend`

**Location:** `/src/server/modules/storage/service.py`

**Syntax:** `backend() -> StorageBackend`

**Response Format:** Configured StorageBackend instance

**Behavior/Conditions:** Select adapter by CMMS_STORAGE__BACKEND (local|minio|s3)

---

#### `tenant_key`

**Location:** `/src/server/modules/storage/service.py`

**Syntax:** `tenant_key(org_id: UUID, category: str, *parts) -> str`

**Inputs:** `org_id`: Organization ID; `category`: Category like attachments/manuals; `*parts`: Additional path components

**Response Format:** Normalized storage key

**Behavior/Conditions:** Builds '/org-{org_id}/{category}/...' paths; Rejects '..' and absolute segments

---

#### `put`

**Location:** `/src/server/modules/storage/service.py`

**Syntax:** `async put(key, stream, mime, max_bytes) -> int`

**Inputs:** `key`: Storage key; `stream`: Binary stream; `mime`: MIME type; `max_bytes`: Max size limit

**Response Format:** Bytes written

**Behavior/Conditions:** Streaming upload with SIZE_EXCEEDED abort

---

#### `get`

**Location:** `/src/server/modules/storage/service.py`

**Syntax:** `async get(key) -> AsyncIterator[bytes]`

**Inputs:** `key`: Storage key

**Response Format:** File chunks iterator

**Behavior/Conditions:** Streaming download

---

#### `delete`

**Location:** `/src/server/modules/storage/service.py`

**Syntax:** `async delete(key) -> None`

**Inputs:** `key`: Storage key

**Response Format:** None

**Behavior/Conditions:** Idempotent delete

---

#### `exists`

**Location:** `/src/server/modules/storage/service.py`

**Syntax:** `async exists(key) -> bool`

**Inputs:** `key`: Storage key

**Response Format:** True if exists

**Behavior/Conditions:** Head object check

---

#### `presigned_url`

**Location:** `/src/server/modules/storage/service.py`

**Syntax:** `async presigned_url(key, ttl_s=900, method='GET') -> str`

**Inputs:** `key`: Storage key; `ttl_s`: Validity seconds; `method`: HTTP method

**Response Format:** Presigned URL string

**Behavior/Conditions:** Max 1h TTL cap enforced

---

#### `sniff_mime`

**Location:** `/src/server/modules/storage/service.py`

**Syntax:** `sniff_mime(head: bytes) -> str`

**Inputs:** `head`: First bytes of file

**Response Format:** MIME type string

**Behavior/Conditions:** Uses python-magic; Falls back to application/octet-stream

---

#### `health_check`

**Location:** `/src/server/modules/storage/service.py`

**Syntax:** `async health_check() -> HealthReport`

**Response Format:** HealthReport

**Behavior/Conditions:** Write-read-delete probe; UNAVAILABLE on failure

---

#### `provider`

**Location:** `/src/server/modules/email/service.py`

**Syntax:** `provider() -> EmailProvider`

**Response Format:** Configured EmailProvider instance

**Behavior/Conditions:** Select adapter by CMMS_EMAIL__PROVIDER (smtp|api)

---

#### `render`

**Location:** `/src/server/modules/email/service.py`

**Syntax:** `render(template, vars) -> RenderedEmail`

**Inputs:** `template`: Template name; `vars`: Template variables

**Response Format:** RenderedEmail{subject, html, text}

**Behavior/Conditions:** Supports verify_email|password_reset|invitation templates

---

#### `send`

**Location:** `/src/server/modules/email/service.py`

**Syntax:** `async send(to, subject, html, text) -> bool`

**Inputs:** `to`: Recipient email; `subject`: Email subject; `html`: HTML body; `text`: Plain text body

**Response Format:** True if sent successfully

**Behavior/Conditions:** 3 retries exponential backoff; Redact addresses except domain

---

#### `send_template`

**Location:** `/src/server/modules/email/service.py`

**Syntax:** `async send_template(template, to, vars) -> bool`

**Inputs:** `template`: Template name; `to`: Recipient email; `vars`: Template variables

**Response Format:** True if sent successfully

**Behavior/Conditions:** Main entrypoint for templated emails

---

#### `health_check`

**Location:** `/src/server/modules/email/service.py`

**Syntax:** `async health_check() -> HealthReport`

**Response Format:** HealthReport

**Behavior/Conditions:** Provider handshake test

---

### Chunk 10 - files_module

#### `validate_upload`

**Features:** allowed JPEG/PNG/PDF/TXT/DOCX (+config); max 10MB default; BOTH extension and MIME checked; sniffed MIME must match claimed; executables blocked; returns violation codes {MIME_INVALID, EXT_BLOCKED, SIZE_EXCEEDED, EXECUTABLE_BLOCKED}

---

#### `upload`

**Route:** `POST /files/upload`

**Features:** validate_upload -> STORAGE.tenant_key -> STORAGE.put; persist metadata row {original_name, key, mime, size, uploaded_by, entity_type, entity_id, purpose}; emit file.uploaded; audited; rate-limited

---

#### `get_file`

**Route:** `GET /files/{id}`

**Features:** org+permission check on linked entity

---

#### `download_url`

**Route:** `GET /files/{id}/download-url`

**Features:** verify caller org + entity permission; STORAGE.presigned_url (15 min)

---

#### `delete_file`

**Route:** `DELETE /files/{id}`

**Features:** soft-delete metadata; STORAGE.delete; blocked where retention/audit requires; emit file.deleted; audited

---

#### `list_for_entity`

**Route:** `GET /files/entity/{entity_type}/{entity_id}`

**Features:** all files linked to entity (node manuals, WO attachments, ticket attachments); optional purpose filter

---

#### `attach`

**Features:** link existing file to entity; THE port used by WORKORDERS/TICKETS/ASSETS

---

#### `mark_for_ingestion`

**Route:** `POST /files/{id}/ingest`

**Required Roles:** MANAGER, MAINTENANCE

**Features:** only PDF/TXT/DOCX; set ingestion_status=PENDING; emit manual.ingestion_requested{file_id, org_id, node_id}; AI module consumes

---

#### `set_ingestion_status`

**Features:** port for AI callbacks; status in {PENDING, PROCESSING, COMPLETED, FAILED}

---

#### `duplicate_policy`

**Features:** org-configured duplicate handling; returns DupDecision{reject|version|allow} based on content_hash

---

### Chunk 10 - tickets_module

#### `create_ticket`

**Route:** `POST /tickets`

**Required Roles:** OPERATOR, MANAGER

**Features:** TENANCY.can_create_ticket payment gate; node ACTIVE validation; OPEN status routed to Maintenance Pool; file attachments via FILES; emit ticket.created; NTF notify_role(MAINTENANCE); audited

---

#### `list_tickets`

**Route:** `GET /tickets`

**Features:** org+role scoped; pagination

---

#### `get_ticket`

**Route:** `GET /tickets/{id}`

**Features:** ticket + reports + feedbacks + assignments + full event history

---

#### `claim`

**Route:** `POST /tickets/{id}/claim`

**Required Roles:** MAINTENANCE

**Features:** OPEN->IN_PROGRESS; assignment=claimant; ticket_assignments row; emit ticket.claimed; NTF issuer; audited

---

#### `assign`

**Route:** `POST /tickets/{id}/assign`

**Required Roles:** MANAGER

**Features:** manual assignment; reassignment audited; emit ticket.assigned; NTF assignee

---

#### `submit_report`

**Route:** `POST /tickets/{id}/report`

**Required Roles:** MAINTENANCE

**Features:** IN_PROGRESS->REPORT_SUBMITTED; ticket_reports row with work performed/findings/attachments; emit ticket.report_submitted; NTF issuer

---

#### `submit_feedback`

**Route:** `POST /tickets/{id}/feedback`

**Required Roles:** OPERATOR, MANAGER

**Features:** REPORT_SUBMITTED->ISSUER_FEEDBACK_REQUIRED->back to IN_PROGRESS; loop_counter++; if loop_counter>3 auto-escalate; emit ticket.feedback_requested

---

#### `accept_ticket`

**Route:** `POST /tickets/{id}/accept`

**Required Roles:** issuer

**Features:** ->ISSUER_ACCEPTED then CLOSED; emit ticket.accepted + ticket.closed; NTF maintenance

---

#### `escalate`

**Route:** `POST /tickets/{id}/escalate`

**Required Roles:** issuer, MANAGER

**Features:** ->ESCALATED_TO_MANAGER; emit ticket.escalated; NTF managers

---

#### `manager_decision`

**Route:** `POST /tickets/{id}/decision`

**Required Roles:** MANAGER

**Features:** decision in {FORCE_CLOSE, REQUIRE_NEW_TICKET, MANDATE_ACTION}; resolving escalation per baseline 12

---

#### `assert_transition`

**Features:** 5-step state machine OPEN->IN_PROGRESS->REPORT_SUBMITTED->ISSUER_FEEDBACK_REQUIRED->ISSUER_ACCEPTED->CLOSED with ESCALATED_TO_MANAGER branch; raise InvalidTransition

---

#### `loop_guard`

**Features:** persisted loop counter for steps 3<->4; max 3 repetitions

---

#### `for_node`

**Features:** TicketNodeView port; active + historical tickets for node

---

### Chunk 11 - ai_module

#### `provider`

**Features:** AIGateway protocol; adapter selection by CMMS_AI__PROVIDER

---

#### `sanitize_prompt`

**Features:** PII stripping; org_id redaction; email masking

---

#### `generate_checklist`

**Route:** `POST /ai/checklists/generate`

**Required Roles:** MANAGER, SYS_ADMIN

**Features:** prompt length validation; sanitization; job creation; worker dispatch

---

#### `generate_checklist_async`

**Features:** JSON schema validation; retry on invalid JSON (3x); result persistence; event emission

---

#### `get_generation`

**Route:** `GET /ai/generations/{id}`

**Features:** status retrieval; result fetching

---

#### `ingest_manual`

**Features:** file fetch via STORAGE; text extraction; chunking with metadata; embedding via provider; pgvector upsert

---

#### `retry_failed_ingestions`

**Features:** failed job retry

---

#### `ask_assistant`

**Route:** `POST /ai/assistant/threads/{id}/messages`

**Features:** pgvector similarity search; org+node filtering; grounded answer with citations; fallback response

---

#### `create_thread`

**Route:** `POST /ai/assistant/threads`

**Features:** thread creation; optional node binding

---

#### `get_messages`

**Route:** `GET /ai/assistant/threads/{id}/messages`

**Features:** thread history retrieval

---

#### `reprocess_manual`

**Route:** `POST /ai/manuals/{fileId}/reprocess`

**Required Roles:** MANAGER, MAINTENANCE

**Features:** manual re-ingestion trigger

---

#### `log_usage`

**Features:** token tracking; quota enforcement support

---

### Chunk 11 - files_module

#### `validate_upload`

**Features:** extension check; MIME sniffing; size validation; executable detection

---

#### `upload`

**Route:** `POST /files/upload`

**Features:** policy validation; tenant_key generation; STORAGE.put; metadata persistence; event emission

---

#### `get_file`

**Route:** `GET /files/{id}`

**Features:** org+permission check

---

#### `download_url`

**Route:** `GET /files/{id}/download-url`

**Features:** presigned URL (15 min TTL)

---

#### `delete_file`

**Route:** `DELETE /files/{id}`

**Features:** soft-delete; STORAGE.delete; event emission

---

#### `list_for_entity`

**Route:** `GET /files/entity/{entity_type}/{entity_id}`

**Features:** entity-linked files; purpose filter

---

#### `attach`

**Features:** THE port for WORKORDERS/TICKETS/ASSETS

---

#### `mark_for_ingestion`

**Route:** `POST /files/{id}/ingest`

**Required Roles:** MANAGER, MAINTENANCE

**Features:** PDF/TXT/DOCX only; emits manual.ingestion_requested

---

#### `set_ingestion_status`

**Features:** AI callback port; status: PENDING|PROCESSING|COMPLETED|FAILED

---

#### `duplicate_policy`

**Features:** org-configured: REJECT|VERSION|ALLOW

---


## State Machines

### tickets_module (Chunk 10)

| State | Transitions |
|-------|-------------|
| CLOSED | CLOSED -> terminal |
| ESCALATED_TO_MANAGER | ESCALATED_TO_MANAGER -> FORCE_CLOSE, REQUIRE_NEW_TICKET, MANDATE_ACTION |
| IN_PROGRESS | IN_PROGRESS -> REPORT_SUBMITTED, ESCALATED_TO_MANAGER |
| ISSUER_ACCEPTED | ISSUER_ACCEPTED -> CLOSED |
| ISSUER_FEEDBACK_REQUIRED | ISSUER_FEEDBACK_REQUIRED -> IN_PROGRESS, ESCALATED_TO_MANAGER |
| OPEN | OPEN -> IN_PROGRESS, ESCALATED_TO_MANAGER |
| REPORT_SUBMITTED | REPORT_SUBMITTED -> ISSUER_FEEDBACK_REQUIRED, ISSUER_ACCEPTED |

---


## Module Exports

### Chunk 1 - Core Kernel & Module System

| Export | Purpose |
|--------|----------|
| `ModuleBase` | Core module public API - exports all kernel functions |
| `ModuleMeta` | Core module public API - exports all kernel functions |
| `Application` | Core module public API - exports all kernel functions |
| `HealthReport` | Core module public API - exports all kernel functions |
| `HealthStatus` | Core module public API - exports all kernel functions |
| `SettingsBundle` | Core module public API - exports all kernel functions |
| `DependencyCycleError` | Core module public API - exports all kernel functions |
| `UnknownDependencyError` | Core module public API - exports all kernel functions |
| `discover_modules` | Core module public API - exports all kernel functions |
| `validate_dependency_graph` | Core module public API - exports all kernel functions |
| `topological_order` | Core module public API - exports all kernel functions |
| `boot` | Core module public API - exports all kernel functions |
| `shutdown` | Core module public API - exports all kernel functions |
| `register_service` | Core module public API - exports all kernel functions |
| `get_service` | Core module public API - exports all kernel functions |
| `publish` | Core module public API - exports all kernel functions |
| `subscribe` | Core module public API - exports all kernel functions |
| `load_settings` | Core module public API - exports all kernel functions |
| `module_settings` | Core module public API - exports all kernel functions |
| `get_logger` | Core module public API - exports all kernel functions |
| `utcnow` | Core module public API - exports all kernel functions |
| `new_id` | Core module public API - exports all kernel functions |
| `new_request_id` | Core module public API - exports all kernel functions |
| `poll_health` | Core module public API - exports all kernel functions |
| `supervise` | Core module public API - exports all kernel functions |
| `feature_enabled` | Core module public API - exports all kernel functions |
| `HealthStatus` | Class defined in Abstract base class for all modules |
| `ModuleMeta` | Class defined in Abstract base class for all modules |
| `ModuleContext` | Class defined in Abstract base class for all modules |
| `ModuleBase` | Class defined in Abstract base class for all modules |
| `ServiceNotRegisteredError` | Class defined in Typed service registry for cross-module communication |
| `InterfaceMismatchError` | Class defined in Typed service registry for cross-module communication |
| `DuplicateServiceError` | Class defined in Typed service registry for cross-module communication |
| `ServiceRegistry` | Class defined in Typed service registry for cross-module communication |
| `Subscription` | Class defined in Async event publishing with subscriber isolation |
| `EventBus` | Class defined in Async event publishing with subscriber isolation |
| `SettingsLoadError` | Class defined in Environment-based configuration with Pydantic validation |
| `ModuleSettingsWrapper` | Class defined in Environment-based configuration with Pydantic validation |
| `SettingsBundle` | Class defined in Environment-based configuration with Pydantic validation |
| `SettingsLoader` | Class defined in Environment-based configuration with Pydantic validation |
| `DependencyCycleError` | Class defined in Dependency graph validation and topological sorting |
| `UnknownDependencyError` | Class defined in Dependency graph validation and topological sorting |
| `DependencyGraphValidator` | Class defined in Dependency graph validation and topological sorting |
| `DuplicateModuleError` | Class defined in Module discovery by scanning package for ModuleBase subclasses |
| `Application` | Class defined in Boot orchestration - coordinates full module lifecycle |
| `BootOrchestrator` | Class defined in Boot orchestration - coordinates full module lifecycle |
| `HealthReport` | Class defined in Concurrent module health polling |
| `HealthPoller` | Class defined in Concurrent module health polling |
| `Supervisor` | Class defined in Background health monitoring and degradation propagation |
| `StructuredFormatter` | Class defined in Structured JSON logging with module namespacing |
| `ModuleLoggerAdapter` | Class defined in Structured JSON logging with module namespacing |
| `RequestLoggerFilter` | Class defined in Structured JSON logging with module namespacing |
| `Role` | Class defined in Shared types and domain errors |
| `HealthStatus` | Class defined in Shared types and domain errors |
| `RequestContext` | Class defined in Shared types and domain errors |
| `Page` | Class defined in Shared types and domain errors |
| `ErrorResponse` | Class defined in Shared types and domain errors |
| `DomainError` | Class defined in Shared types and domain errors |
| `NotFoundError` | Class defined in Shared types and domain errors |
| `ForbiddenError` | Class defined in Shared types and domain errors |
| `UnauthorizedError` | Class defined in Shared types and domain errors |
| `QuotaExceededError` | Class defined in Shared types and domain errors |
| `InvalidTransitionError` | Class defined in Shared types and domain errors |

---

### Chunk 2 - Infrastructure Layer - DB, Cache, Storage, Email

| Export | Purpose |
|--------|----------|
| `build_engine` | DB module public API exports |
| `session_factory` | DB module public API exports |
| `org_scoped_session` | DB module public API exports |
| `ensure_extensions` | DB module public API exports |
| `run_migrations` | DB module public API exports |
| `transaction` | DB module public API exports |
| `register_models` | DB module public API exports |
| `health_check` | DB module public API exports |
| `DatabaseService` | DB module public API exports |
| `DBSettings` | Class defined in PostgreSQL access with RLS, migrations, and health reporting |
| `DatabaseService` | Class defined in PostgreSQL access with RLS, migrations, and health reporting |
| `DBModule` | Class defined in PostgreSQL access with RLS, migrations, and health reporting |
| `connect` | Cache module public API exports |
| `allow` | Cache module public API exports |
| `lock` | Cache module public API exports |
| `delay_schedule` | Cache module public API exports |
| `delay_due` | Cache module public API exports |
| `kv_get` | Cache module public API exports |
| `kv_set` | Cache module public API exports |
| `kv_delete` | Cache module public API exports |
| `broker_url` | Cache module public API exports |
| `health_check` | Cache module public API exports |
| `RateDecision` | Cache module public API exports |
| `DelayedJob` | Cache module public API exports |
| `CacheService` | Cache module public API exports |
| `RateDecision` | Class defined in Redis services for rate limiting, locks, delayed queues, KV cache |
| `DelayedJob` | Class defined in Redis services for rate limiting, locks, delayed queues, KV cache |
| `CacheService` | Class defined in Redis services for rate limiting, locks, delayed queues, KV cache |
| `CacheModule` | Class defined in Redis services for rate limiting, locks, delayed queues, KV cache |
| `backend` | Storage module public API exports |
| `tenant_key` | Storage module public API exports |
| `put` | Storage module public API exports |
| `get` | Storage module public API exports |
| `delete` | Storage module public API exports |
| `exists` | Storage module public API exports |
| `presigned_url` | Storage module public API exports |
| `sniff_mime` | Storage module public API exports |
| `health_check` | Storage module public API exports |
| `StorageService` | Storage module public API exports |
| `StorageBackend` | Class defined in Object storage abstraction with local, MinIO, S3 adapters |
| `LocalBackend` | Class defined in Object storage abstraction with local, MinIO, S3 adapters |
| `S3Backend` | Class defined in Object storage abstraction with local, MinIO, S3 adapters |
| `StorageService` | Class defined in Object storage abstraction with local, MinIO, S3 adapters |
| `StorageModule` | Class defined in Object storage abstraction with local, MinIO, S3 adapters |
| `provider` | Email module public API exports |
| `render` | Email module public API exports |
| `send` | Email module public API exports |
| `send_template` | Email module public API exports |
| `health_check` | Email module public API exports |
| `RenderedEmail` | Email module public API exports |
| `EmailService` | Email module public API exports |
| `RenderedEmail` | Class defined in Transactional email with SMTP and API provider adapters |
| `EmailProvider` | Class defined in Transactional email with SMTP and API provider adapters |
| `SMTPProvider` | Class defined in Transactional email with SMTP and API provider adapters |
| `APIProvider` | Class defined in Transactional email with SMTP and API provider adapters |
| `EmailService` | Class defined in Transactional email with SMTP and API provider adapters |
| `EmailModule` | Class defined in Transactional email with SMTP and API provider adapters |

---


## Event Catalog

### Emitted Events

| Chunk | Module | Event |
|-------|--------|-------|
| 10 | tickets_module | ticket.created |
| 10 | tickets_module | ticket.claimed |
| 10 | tickets_module | ticket.assigned |
| 10 | tickets_module | ticket.report_submitted |
| 10 | tickets_module | ticket.feedback_requested |
| 10 | tickets_module | ticket.accepted |
| 10 | tickets_module | ticket.escalated |
| 10 | tickets_module | ticket.closed |
| 10 | files_module | file.uploaded |
| 10 | files_module | file.deleted |
| 10 | files_module | manual.ingestion_requested |
| 11 | ai_module | ai.checklist_completed |
| 11 | ai_module | ai.checklist_failed |
| 11 | ai_module | ai.ingestion_completed |
| 11 | ai_module | ai.ingestion_failed |
| 11 | ai_module | ai.assistant_answered |
| 11 | files_module | file.uploaded |
| 11 | files_module | file.deleted |
| 11 | files_module | manual.ingestion_requested |

---

### Consumed Events

| Chunk | Module | Event |
|-------|--------|-------|
| 11 | ai_module | manual.ingestion_requested |

---


## Database Tables

### Chunk 10 - files_module

| Table Name |
|------------|
| files |
| work_order_attachments |

---

### Chunk 10 - tickets_module

| Table Name |
|------------|
| tickets |
| ticket_reports |
| ticket_feedbacks |
| ticket_assignments |
| ticket_events |

---

### Chunk 11 - ai_module

| Table Name |
|------------|
| document_ingestion_jobs |
| document_chunks |
| ai_generation_jobs |
| ai_assistant_threads |
| ai_assistant_messages |
| ai_usage_logs |

---

### Chunk 11 - files_module

| Table Name |
|------------|
| files |
| work_order_attachments |

---

