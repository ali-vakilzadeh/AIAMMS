# CMMS SaaS — Server Application Architecture
## Modular Monolith, Core-Orchestrated, API-First

**Reference baseline:** `architecture.txt` (Open-Source CMMS SaaS — MVP Architecture, incl. AI Phase 1/2 and MCP Server)
**This document:** Refines that baseline into a **server-side modular architecture** under the following deployment assumptions:

| # | Component | Location | Notes |
|---|-----------|----------|-------|
| 1 | **Server** (this document) | Own server(s) | Accepts traffic **only via REST API** (`/api/v1`) plus a **separate MCP interface** (`/mcp/*` or stdio). Serves no UI. |
| 2 | **Web UI** | Separate server/host | React SPA consuming the REST API. Static hosting, CDN, or any web server — outside this server. |
| 3 | **Mobile clients** | Devices | PWA or native Android consuming the same REST API (refresh-token persistent login). |

---

# 1. Design Principles

1. **Microkernel / plugin structure.** A thin `core` kernel boots, supervises, health-checks, and wires modules. `core` contains **zero CMMS business logic**.
2. **Modules own their domain.** Each module owns its routes, services, tasks, events, settings schema, and (logically) its tables.
3. **Stable contracts, swappable implementations.** Cross-module calls go through **ports** (typed interfaces published in the service registry), never through another module's internals. External systems (AI provider, storage, email, broker) sit behind **adapters** selected by configuration.
4. **Events for decoupling.** Modules that must not depend on each other directly communicate via the in-process **event bus** (e.g., `CYCLES → WORKORDERS` generation).
5. **One codebase, multiple entrypoints.** The same module set produces the `api`, `worker`, `beat`, and `mcp` processes via **runtime profiles**.
6. **Parity of enforcement.** REST and MCP both call the **same domain services**; multi-tenancy, RBAC, RLS, tier limits, payment blocks, and safety rules are enforced once, in the modules.
7. **Everything is health-reportable.** Every module implements a uniform `health()` contract; `core` aggregates it for `/health/live` and `/health/ready`.

---

# 2. Module System (the Kernel Contract)

## 2.1 Module contract

Every module implements this protocol (enforced by `core`):

```python
# core/module.py
class ModuleBase(ABC):
    name: ClassVar[str]                          # unique module id, e.g. "assets"
    version: ClassVar[str]                       # semver, logged at boot
    dependencies: ClassVar[tuple[str, ...]]      # hard deps (boot order)
    optional_dependencies: ClassVar[tuple[str, ...]] = ()
    profiles: ClassVar[tuple[str, ...]] = ("api", "worker", "beat", "mcp")

    async def configure(self, settings: SettingsBundle) -> None: ...
    async def initialize(self, ctx: ModuleContext) -> None: ...   # DI happens here
    async def start(self) -> None: ...                              # listeners, timers
    async def stop(self) -> None: ...                               # graceful drain
    async def health(self) -> HealthReport: ...
```

`ModuleContext` (injected by core) provides:
- `ctx.services.get("<port-name>")` — typed access to other modules' published interfaces;
- `ctx.events` — publish/subscribe event bus;
- `ctx.settings.module("<name>")` — the module's own validated settings;
- `ctx.logger` — structured logger namespaced to the module;
- `ctx.db` — session factory (only if `db` is declared as a dependency);
- `ctx.register_api_router(...)`, `ctx.register_tasks(...)`, `ctx.register_beat_schedule(...)` — contribution hooks.

## 2.2 Lifecycle managed by `core`

```
discover → validate graph (cycle detection) → topological sort
→ configure (settings validation) → initialize (dependency injection)
→ start → SUPERVISE LOOP (periodic health poll, restart policy)
→ graceful stop (reverse topological order, drain in-flight work)
```

## 2.3 Cross-module rules

| Rule | Enforcement |
|---|---|
| Modules import only `core` + declared dependencies' **public ports** | Linter rule + CI import graph check |
| No cross-module ORM joins; read other modules via their services/events | Code review + contract tests |
| Domain tables are owned by exactly one module | Documented ownership map (§13) |
| All inbound calls (REST or MCP) pass the same domain service | MCP module wraps services, never re-implements |

## 2.4 Runtime profiles & entrypoints

| Profile | Process | Modules loaded (beyond core+infra) |
|---|---|---|
| `api` | FastAPI/Uvicorn | API, AUTH, TENANCY, AUDIT, NOTIFY, ASSETS, TEMPLATES, CYCLES, WORKORDERS, TICKETS, FILES, REPORTS, AI |
| `worker` | Celery worker | WORKER + task-owning modules (CYCLES, WORKORDERS, TENANCY, NOTIFY, ASSETS, REPORTS, FILES, AI, AUDIT) |
| `beat` | Celery Beat | WORKER (scheduler) + beat schedule manifests |
| `mcp` | MCP server | MCP + all domain service modules it wraps (no HTTP routes mounted) |
| `all-in-one` | dev convenience | everything in one process |

---

# 3. Module Inventory

| Layer | Modules |
|---|---|
| **Kernel** | `CORE` |
| **Infrastructure** | `DB`, `CACHE`, `STORAGE`, `EMAIL`, `WORKER`, `OBSERVABILITY` |
| **Platform** | `API`, `AUTH`, `TENANCY`, `AUDIT`, `NOTIFY` |
| **Domain** | `ASSETS`, `TEMPLATES`, `CYCLES`, `WORKORDERS`, `TICKETS`, `FILES`, `REPORTS` |
| **Extensions** | `AI`, `MCP` |

```
                    ┌─────────────────────────────────────────────┐
   REST /api/v1 ──▶ │  API ─ AUTH ─ TENANCY ─ AUDIT ─ NOTIFY      │ Platform
                    ├─────────────────────────────────────────────┤
   MCP /mcp/*  ──▶  │  MCP                                        │ Extensions
                    ├─────────────────────────────────────────────┤
                    │  ASSETS  TEMPLATES  CYCLES  WORKORDERS      │ Domain
                    │  TICKETS  FILES     REPORTS                 │
                    ├─────────────────────────────────────────────┤
                    │  AI (providers · checklist gen · RAG)       │ Extensions
                    ├─────────────────────────────────────────────┤
                    │  DB · CACHE · STORAGE · EMAIL · WORKER ·    │ Infrastructure
                    │  OBSERVABILITY                              │
                    ├─────────────────────────────────────────────┤
                    │                CORE (kernel)                │
                    └─────────────────────────────────────────────┘
```

---

# 4. `CORE` — Application Kernel

**Owns:** lifecycle only. **Owns nothing CMMS.**

### Responsibilities
1. **Boot orchestration** — module discovery (package scan / entry points), dependency-graph validation (cycle detection → boot failure with explicit error), topological init/start order, reverse-order shutdown.
2. **Service registry** — typed publish/lookup of module ports (`register_service`, `get_service`); double-registration and missing-dependency detection.
3. **Event bus** — in-process async pub/sub; subscriber failure isolation (a failing listener never breaks the publisher); support for *post-commit* listeners (fire after DB transaction commit) for consistency.
4. **Configuration kernel** — env-variable loading, per-module settings namespaces, validation via pydantic-settings, feature flags (`CMMS_FEATURE_<FLAG>`), module enable/disable per profile.
5. **Secrets handling** — secrets only from environment / secret manager; never logged; redaction helper shared with logging.
6. **Supervision** — periodic `health()` polling of all modules; degradation propagation (if a hard dep is DOWN, dependents report DEGRADED); configurable restart policy per module; module status exposed to `OBSERVABILITY`.
7. **Time & identity utilities** — UTC clock provider, request-id generator, correlation-id propagation.
8. **Logging kernel** — structured JSON logging setup, request-id correlation, module-namespaced loggers.

### Explicit non-responsibilities
No domain tables, no CMMS rules, no HTTP routing, no task definitions.

### Health
Self-checks: registry integrity, event-bus liveness, config validity.

---

# 5. Infrastructure Modules

## 5.1 `DB` — PostgreSQL Access

| Aspect | Detail |
|---|---|
| **Responsibilities** | Async engine + connection pool (SQLAlchemy 2 / asyncpg); session factory; **RLS context injection** (`SET app.organization_id = :org` on every tenant session); transaction helpers; Alembic migration runner hook; pgvector extension bootstrap; slow-query logging hooks. |
| **Does NOT** | Define domain schemas per se (modules own their models); contain queries. |
| **Published ports** | `DatabaseService`: `session_factory`, `org_scoped_session(org_id)`, `migrate()`, `extensions_ready()` |
| **External deps** | PostgreSQL 15+ with `pgvector` |
| **Internal deps** | `CORE` |
| **Consumed by** | Every stateful module |
| **Config** | `CMMS_DB__URL`, `POOL_SIZE`, `MAX_OVERFLOW`, `POOL_TIMEOUT`, `STATEMENT_TIMEOUT`, `RLS_ENFORCED` |
| **Health** | Connectivity ping, pool saturation %, replication lag (if configured) |
| **Extension point** | Dialect/DSN swap isolated here; if a second datastore is ever needed, modules consume it via this module's port only. |

## 5.2 `CACHE` — Redis Services

| Aspect | Detail |
|---|---|
| **Responsibilities** | Redis connection management; **rate-limit service** (fixed/sliding window per IP/user/org/tool); **distributed locks** (idempotent cycle evaluation, MCP batch ops); **delayed queues** (snooze expiration, scheduled reminders); short-lived KV cache; Celery broker URL provider. |
| **Published ports** | `RateLimiter.allow(key, limit, window)`, `LockService.acquire(name, ttl)`, `DelayQueue.schedule(task, at)`, `KVCache`, `BrokerInfo` |
| **External deps** | Redis 7+ |
| **Internal deps** | `CORE` |
| **Config** | `CMMS_CACHE__URL`, `RATE_LIMIT_DEFAULT`, `RATE_LIMIT_AI`, `RATE_LIMIT_MCP_WRITE`, `LOCK_DEFAULT_TTL` |
| **Health** | Connectivity, latency, memory pressure |

## 5.3 `STORAGE` — Object Storage Abstraction

| Aspect | Detail |
|---|---|
| **Responsibilities** | Byte-level storage only: `put/get/delete/exists/presigned_url/metadata`; **tenant-scoped key policy** enforced centrally (`/org-{id}/attachments|manuals|exports/...`); MIME sniffing helper; size-limit enforcement at stream level; short-lived presigned URL issuance. |
| **Does NOT** | Store file metadata in DB (owned by `FILES`), decide ingestion policy (owned by `AI`). |
| **Published ports** | `StorageBackend` interface; default selection via config. |
| **Adapters** | `local` (filesystem), `minio`, `s3` (any S3-compatible). New adapter = one new class + config switch; **zero changes elsewhere**. |
| **External deps** | MinIO / S3 / local disk |
| **Internal deps** | `CORE` |
| **Config** | `CMMS_STORAGE__BACKEND`, `BUCKET_ROOT`, `PRESIGN_TTL_SECONDS`, `MAX_UPLOAD_BYTES` (default 10 MB) |
| **Health** | Bucket reachability, write probe |

## 5.4 `EMAIL` — Transactional Email

| Aspect | Detail |
|---|---|
| **Responsibilities** | Send-only transactional email for **authentication flows only** (verification, password reset, invitations); provider abstraction; template rendering (plain templates live here); delivery retry with backoff; bounce/suppression handling per provider. |
| **Published ports** | `EmailProvider.send(message)`; `EmailService.send_template(template, to, vars)` |
| **Adapters** | `smtp`, `api_provider` (any transactional API). Swappable by config. |
| **Consumers** | `AUTH`, `TENANCY` (invitations) — always via port. |
| **Internal deps** | `CORE` |
| **Config** | `CMMS_EMAIL__PROVIDER`, `SMTP_*`, `API_KEY`, `FROM_ADDRESS` |
| **Health** | Provider reachability (dry handshake), queue depth |
| **Note** | No operational email in MVP — this module is deliberately tiny; operational notifications belong to `NOTIFY` (in-app). |

## 5.5 `WORKER` — Background Job Engine

| Aspect | Detail |
|---|---|
| **Responsibilities** | Celery app factory; **task registry** — each module contributes tasks via `ctx.register_tasks(...)`; **beat schedule registry** — modules contribute schedules; idempotency decorator (uses `CACHE` locks); retry policy (exponential backoff, max retries, dead-letter queue); task observability (task id, status, failure reason persisted); distributed single-flight for scheduled jobs. |
| **Published ports** | `TaskEngine.dispatch(task_name, args, countdown=, idempotency_key=)`, `register_task`, `register_beat` |
| **Internal deps** | `CORE`, `CACHE` (broker) |
| **Hosted tasks (contributed by modules)** | See each domain module's "Background tasks" row; global beat table in §10. |
| **Config** | `CMMS_WORKER__CONCURRENCY`, `PREFETCH`, `TASK_TIME_LIMIT`, `DLQ_ENABLED` |
| **Health** | Broker connectivity, queue depth, worker heartbeat, oldest-task age |

## 5.6 `OBSERVABILITY` — Health, Metrics, Diagnostics

| Aspect | Detail |
|---|---|
| **Responsibilities** | Aggregates `core` module-health reports; serves `/health/live` and `/health/ready`; structured metrics (request latency, error rates, queue length, cycle eval success, AI latency, RAG latency, upload failures); request-id correlation auditing; admin module-status endpoint (SYS_ADMIN only); optional Prometheus exporter; failed-job inspector view data. |
| **Internal deps** | `CORE`, `API` (mounts health routes) |
| **Health** | N/A — it *is* the health surface; self-probes via core. |

---

# 6. Platform Modules

## 6.1 `API` — HTTP Surface (FastAPI)

| Aspect | Detail |
|---|---|
| **Responsibilities** | FastAPI app factory; **router registry** — each module mounts its own router under `/api/v1`; middleware chain: request-id → CORS (Web UI and mobile origins) → authentication (hook implemented by `AUTH`) → org-scope binding (hook implemented by `TENANCY`) → rate limiting (via `CACHE`) → handler; standard error envelope `{error_code, message, details}`; pagination convention `{page, page_size, total}`; OpenAPI/Swagger generation; CSRF protection for cookie-based refresh flows; CSP-compatible headers. **Serves no static files** (UI is hosted elsewhere). |
| **Published ports** | `HttpApi.register_router`, `add_middleware`, `add_exception_handler`, `require_permission(...)` decorator helpers |
| **Internal deps** | `CORE` only (AUTH/TENANCY register *into* it — no reverse dependency) |
| **Config** | `CMMS_API__HOST`, `PORT`, `CORS_ORIGINS`, `RATE_LIMIT_*`, `OPENAPI_ENABLED` |
| **Health** | HTTP self-probe, middleware pipeline check |

## 6.2 `AUTH` — Identity, Tokens, RBAC Engine

| Aspect | Detail |
|---|---|
| **Responsibilities** | Signup, email verification, login, logout, refresh rotation (15-min JWT access / 7-day HttpOnly refresh), password complexity + hashing (Argon2/bcrypt), password recovery (single-use time-limited tokens), session invalidation; **RBAC engine** — roles `SYS_ADMIN, MANAGER, REPORTER, OPERATOR, MAINTENANCE`; endpoint permission checks; object-level permission helpers; deactivated-user blocking; JWT claims `{user_id, organization_id, role}` consumed by both REST and MCP. |
| **API endpoints** | `POST /auth/signup · login · refresh · logout · forgot-password · reset-password`, `GET /auth/me` |
| **Published ports** | `TokenService.issue/verify/rotate`, `PasswordService`, `RbacService.can(user, action, resource)`, `CurrentUserProvider` |
| **Events emitted** | `user.registered/verified/logged_in/password_reset/role_changed/deactivated` |
| **Internal deps** | `CORE`, `DB`, `CACHE`, `EMAIL`, `API` |
| **External deps** | None |
| **Config** | `JWT_SECRET`, `ACCESS_TTL=15m`, `REFRESH_TTL=7d`, `HASH_ALGO`, `PASSWORD_POLICY_*` |
| **Health** | Token sign/verify self-test, DB reachability |

## 6.3 `TENANCY` — Organizations, Membership, Tiers, Payments

| Aspect | Detail |
|---|---|
| **Responsibilities** | Organization CRUD + profile (name, logo, contact, timezone, 2–3 custom fields, root-zone treatment); **tier & quota service** (Free ≤100 nodes, Pro ≤1000, Ultimate unlimited; counts active service points; structural entities exempt) — exposed as a port so `ASSETS` enforces it at node creation; **payment state** service (overdue orgs blocked from *new* tickets only; consulted by `TICKETS`); invitations (new-user token flow, existing-user lookup, 14-day expiry, single-org membership rule); membership lifecycle (leave/replace); org-level RLS context provider (binds `organization_id` into `DB` sessions and JWT middleware). |
| **API endpoints** | `GET/PATCH /organizations/me`, `GET /organizations/tier`, `POST/GET/DELETE /organizations/invitations…`, `POST /organizations/invitations/accept` |
| **Background tasks** | `expire_invitations` (hourly, Beat) |
| **Published ports** | `OrgContext.current()`, `QuotaService.assert_node_creatable(org_id)`, `PaymentStatusService.can_create_ticket(org_id)`, `MembershipService` |
| **Events emitted** | `org.created/updated`, `invitation.sent/accepted/expired`, `membership.changed`, `payment.overdue/cleared` |
| **Internal deps** | `CORE`, `DB`, `API`, `AUTH`; `EMAIL` for invitation mail |
| **Health** | DB + quota query probe |

## 6.4 `AUDIT` — Immutable Audit Trail

| Aspect | Detail |
|---|---|
| **Responsibilities** | Append-only audit log (no UPDATE/DELETE grants at DB level); captures: auth events, role changes, org/asset/cycle/work-order/ticket state changes, safety-flag changes, counter logs/resets, file ops, AI requests, MCP tool calls, sysadmin overrides; records `{organization_id, actor_id, actor_type(USER|MCP_AGENT), role, action, entity, prev_state, new_state, ip, user_agent, ts}`; transactional writes where practical, batched worker writes for low-criticality events; query API for managers/sysadmin (role-gated); powers the "AI Activity Log" view. |
| **Implementation** | **Event-driven**: subscribes to `*.audited` and all domain events marked auditable; modules never call audit internals directly. |
| **Internal deps** | `CORE`, `DB`; event bus |
| **Health** | Write probe to audit table |

## 6.5 `NOTIFY` — In-App Notifications

| Aspect | Detail |
|---|---|
| **Responsibilities** | Notification center backend: create/read/read-all; unread counts; deep links `{entity_type, entity_id}`; **event-driven generation** — subscribes to domain events (work order assigned/overdue/snooze-expired, ticket lifecycle, cycle failures, AI ingestion/generation results, exports ready); 30-day expiry job; delivery via React Query polling (SSE hook reserved, not implemented in MVP). |
| **API endpoints** | `GET /notifications`, `POST /notifications/{id}/read`, `POST /notifications/read-all` |
| **Background tasks** | `expire_notifications` (daily) |
| **Published ports** | `NotificationService.notify(user_id, type, title, body, link)` (used by modules that need imperative notification) |
| **Events consumed** | most domain events (§11) |
| **Internal deps** | `CORE`, `DB`, `API`, `CACHE` (unread badge cache) |
| **Health** | DB probe + listener registration check |

---

# 7. Domain Modules

## 7.1 `ASSETS` — Hierarchy, Counters, QR, Safety State

| Aspect | Detail |
|---|---|
| **Responsibilities** | Full asset hierarchy: Zone → Zone-child (≤2) → System → Sub-system → Service Point; **max depth 6** enforced at service + DB level; zones (status, address, contact, ≤5 custom fields, geolocation); cross-zone systems via `system_zone_links` (primary link flag); taxonomy/classification + technical specs on systems; service point lifecycle (`ACTIVE / IN_MAINTENANCE / DECOMMISSIONED`); **soft delete everywhere** with child state inheritance; **zone cloning** (background job, states PENDING/PROCESSING/COMPLETED/FAILED); **counters** (hours/count, multiple per node, logs with source MANUAL/INHERITED/RESET/SYSTEM, permission-scoped resets, top-down inheritance flags); **QR/barcode**: stable code per node, server-side generation, print (HTML/PDF), scan resolution endpoint; **asset state service** computing safety-flag propagation (`HOT_INSPECT`, `PAUSE_FOR_INSPECTION`, `STOP_UNTIL_COMPLETE`) upward through parents. |
| **API endpoints** | CRUD `/zones`, `/systems`, `/sub-systems`, `/service-points`; `…/{id}/history`, `…/{id}/manuals`, `…/{id}/counters/log`, `…/{id}/counters/reset`, `GET /qr/resolve/{code}`, `POST /zones/{id}/clone` |
| **Background tasks** | `clone_zone` (heavy), `qr_bulk_generate` |
| **Published ports** | `AssetResolver.get_with_ancestors(id)`, `AssetStateService.flags_effective(node_id)`, `CounterService.log/reset`, `NodeLookup.by_qr(code)` |
| **Events emitted** | `asset.*.created/updated/decommissioned/cloned`, `counter.logged/reset`, `safety_flag.changed` |
| **Internal deps** | `CORE`, `DB`, `API`, `TENANCY` (quota check on node creation, org scope), `STORAGE` (QR label artifacts), `WORKER` |
| **Tier enforcement** | Calls `TENANCY.QuotaService` before creating service points; returns standardized quota error. |

## 7.2 `TEMPLATES` — Workflows & Checklists

| Aspect | Detail |
|---|---|
| **Responsibilities** | Template CRUD (checklists = flat inspection items; workflows = sequential instruction sets with states `TASK/STARTED/COMPLETED/FAILED/PENDING_PREDECESSOR/PERFORMED_BY`); full work-item field set from baseline §11 (predecessors, durations, skills, certifications, tools, safety permit, risk, measurement fields with type/unit/thresholds, digital signature requirement, cost, downtime); auto-generated unique codes (org-unique, editable); item-level search; **snapshot provider** — produces immutable template snapshots consumed by `WORKORDERS` at generation time; template changes never retroact on existing work orders. |
| **API endpoints** | CRUD `/workflows`, `/checklists`; `GET /workflows/search`, `/checklists/search` |
| **Published ports** | `TemplateService.get(id)`, `SnapshotService.snapshot(template_id) -> TemplateSnapshot` |
| **Events emitted** | `template.created/updated/archived` |
| **Internal deps** | `CORE`, `DB`, `API` |
| **Note** | AI-generated drafts arrive via `AI` module and are saved through this module's normal CRUD — AI output is draft-only until a manager saves it. |

## 7.3 `CYCLES` — Maintenance Cycle Engine

| Aspect | Detail |
|---|---|
| **Responsibilities** | Cycle CRUD at any hierarchy scope (zone/system/sub-system/service point); trigger model: **calendar (cron-like), operating hours, operation count**; multiple triggers per cycle with **first-satisfied-wins**; idempotent evaluation; deadline & grace behavior (`FLAG_CRITICAL_STOP`, `WAIT_UNTIL_COMPLETED`); launch mode AUTOMATIC/MANUAL with frequency; suspension (manager-only, pauses generation); **missed-cycle detection** → overdue-flagged work orders; inheritance rules (top-down for counter-based; snapshot semantics preserved); cycle evaluation log retained. |
| **API endpoints** | CRUD `/cycles`; `POST /cycles/{id}/suspend · activate · manual-trigger`; `GET /cycles/{id}/evaluations` |
| **Background tasks** | `evaluate_due_cycles` (Beat, ~1 min), `detect_missed_cycles` (~5 min) |
| **Published ports** | `CycleService.get/active_for(entity)`, `ManualTriggerService` |
| **Events emitted** | `cycle.created/updated/suspended/activated`, **`cycle.due`** (carries trigger context + template ref), `cycle.missed`, `cycle.eval_failed` |
| **Generation decoupling** | `CYCLES` **never calls** `WORKORDERS` directly; it emits `cycle.due`. `WORKORDERS` subscribes and generates — this removes the CYCLES↔WORKORDERS dependency cycle. |
| **Idempotency** | Per-cycle evaluation lock via `CACHE.LockService` + unique constraint `(cycle_id, period_key)` in DB. |
| **Internal deps** | `CORE`, `DB`, `API`, `ASSETS` (entity resolution, counters), `TEMPLATES` (validate assigned template exists), `WORKER`, `CACHE` |

## 7.4 `WORKORDERS` — Execution Engine

| Aspect | Detail |
|---|---|
| **Responsibilities** | Work order generation from `cycle.due` events using `TEMPLATES.SnapshotService`; full status machine `GENERATED → ACKNOWLEDGED → IN_PROGRESS → (BLOCKED/SNOOZED/REJECTED) → OVERDUE → COMPLETED → CLOSED`; idempotent acknowledgment (first-view tracking); rejection with mandatory reason; snooze (1h/6h/12h/1d/3d/6d, reason required, history stored) with reactivation via `CACHE` delayed queue; item-level updates, measurements per data type (NUMERIC/TEXT/BOOLEAN); threaded comments; per-order & per-item attachments (via `FILES`); digital signatures; safety-flag prominence from `ASSETS.AssetStateService`; completion %, cost, downtime, quality-check reviewer. |
| **API endpoints** | `GET /work-orders(/{id})`, `POST …/acknowledge · reject · snooze`, `PATCH …/items/{itemId}`, `POST …/comments · attachments` |
| **Background tasks** | `resume_snoozed_work_orders` (Beat + delayed queue), `flag_overdue_work_orders` |
| **Published ports** | `WorkOrderService.generate_from_cycle(ctx)`, `WorkOrderQuery.for_node(node_id)` (used by MCP/QR view) |
| **Events emitted** | `work_order.generated/acknowledged/rejected/snoozed/resumed/blocked/completed/closed/overdue`, item-level `wo_item.updated/measured/signed` |
| **Internal deps** | `CORE`, `DB`, `API`, `TEMPLATES` (snapshots), `ASSETS` (target + safety state), `CACHE` (delayed queue), `FILES` (attachments), `WORKER` |

## 7.5 `TICKETS` — Repair Ticketing

| Aspect | Detail |
|---|---|
| **Responsibilities** | Ticket creation by OPERATOR/MANAGER; **payment gate** — consults `TENANCY.PaymentStatusService`; overdue orgs blocked with standard error (existing tickets remain accessible); priorities LOW/MEDIUM/HIGH/CRITICAL; maintenance-pool routing, claim by MAINTENANCE, manual assignment by MANAGER (audited); 5-step flow `OPEN → IN_PROGRESS → REPORT_SUBMITTED → ISSUER_FEEDBACK_REQUIRED → ISSUER_ACCEPTED → CLOSED` with escalation path; **feedback loop capped at 3**, then `ESCALATED_TO_MANAGER` (force close / require new ticket / mandate action); full event history. |
| **API endpoints** | `POST /tickets`, `GET /tickets(/{id})`, `POST …/claim · assign · report · feedback · accept · escalate` |
| **Published ports** | `TicketService.create/claim/…`, `TicketQuery.for_node(node_id)` |
| **Events emitted** | `ticket.created/claimed/assigned/report_submitted/feedback_requested/accepted/escalated/closed` |
| **Internal deps** | `CORE`, `DB`, `API`, `ASSETS` (service point), `TENANCY` (payment gate), `WORKER` (optional digests) |

## 7.6 `FILES` — Attachments & Manuals (domain layer)

| Aspect | Detail |
|---|---|
| **Responsibilities** | All attachment/manual domain logic: policy (JPEG/PNG/PDF/TXT/DOCX, 10 MB default, MIME + extension validation, executables blocked); file metadata records (`purpose: ATTACHMENT/MANUAL/PHOTO/EXPORT/AI_INGESTION_ARTIFACT`); linking files to entities (nodes, work orders, items, tickets); manual flagging for AI ingestion with status `PENDING/PROCESSING/COMPLETED/FAILED`; delegates bytes entirely to `STORAGE`; presigned download URLs; deletion rules respecting soft-delete/audit. |
| **API endpoints** | `POST /files/upload`, `GET /files/{id}`, `GET /files/{id}/download-url`, `DELETE /files/{id}` |
| **Published ports** | `FileService.attach(entity, stream, meta)`, `FileQuery.for_entity(entity)` |
| **Events emitted** | `file.uploaded/deleted`, **`manual.ingestion_requested`** (consumed by `AI`) |
| **Internal deps** | `CORE`, `DB`, `API`, `STORAGE`, `TENANCY` (org scoping) |
| **Design note** | Byte storage (`STORAGE`) vs. domain metadata (`FILES`) separation is what keeps S3↔local swaps invisible to CMMS code. |

## 7.7 `REPORTS` — Dashboards & Exports

| Aspect | Detail |
|---|---|
| **Responsibilities** | Manager/Reporter KPIs (overdue WOs, open/escalated tickets, WO status mix, planned vs unplanned, completion rates, safety-flag incidents, priority distribution, inferable downtime); per-user counters (new/active WOs); filtering + org-isolated queries; export pipeline: job creation → worker renders CSV (XLSX optional) → stored tenant-scoped via `STORAGE` → notification with short-lived URL; optional materialized-view refresh. |
| **API endpoints** | `GET /reports/work-orders · tickets · assets`, `POST /reports/export` |
| **Background tasks** | `generate_export`, `refresh_metrics` (~15 min) |
| **Published ports** | `KpiService.dashboard(org_id, filters)` (consumed by MCP) |
| **Internal deps** | `CORE`, `DB`, `API`, `WORKER`, `STORAGE`, `NOTIFY` (export-ready notification) |

---

# 8. `AI` — AI Subsystem (Phase 1 + Phase 2)

The isolation requirement you stated ("all AI code lives in the AI module") is implemented as **one module, three internal layers**:

```
modules/ai/
├── ports.py            # AIGateway port (generate_text / embed / stream)
├── providers/          # ADAPTERS — the only place provider knowledge exists
│   ├── openrouter.py   #   default: OpenRouter (OpenAI-compatible surface)
│   ├── openai.py       #   any OpenAI-compatible endpoint
│   ├── anthropic.py    #   Anthropic-compatible
│   └── local.py        #   Ollama / vLLM / self-hosted (privacy mode)
├── checklist/          # Phase 1: generation service + JSON-schema validation
├── rag/                # Phase 2: ingestion pipeline + retrieval + assistant
└── usage.py            # logs, quotas, rate limits, prompt sanitizer
```

| Aspect | Detail |
|---|---|
| **Responsibilities** | **Provider abstraction** — config selects adapter; timeouts/retries/model names per provider; org-level privacy mode (force local adapter); prompt sanitization (no org id, no PII, no tenant identifiers sent externally). **Phase 1 — Checklist generation**: prompt → structured JSON per schema → validation → retry on invalid → draft returned for manager review (never authoritative); job states PENDING/PROCESSING/COMPLETED/FAILED; generation logs. **Phase 2 — RAG assistant**: ingestion pipeline (extract → chunk → embed → pgvector with metadata `{organization_id, service_point_id, file_id, page, chunk_index, heading, tokens}`); strictly tenant+node-filtered retrieval; top-k + similarity threshold; grounded answers with citations; "not found in manuals" fallback; thread model per user/node; usage logging. |
| **API endpoints** | `POST /ai/checklists/generate`, `GET /ai/generations/{id}`, `POST /ai/assistant/threads`, `POST /ai/assistant/threads/{id}/messages`, `GET /ai/assistant/threads/{id}/messages`, `POST /ai/manuals/{fileId}/reprocess` |
| **Background tasks** | `ingest_manual` (extract/chunk/embed), `generate_checklist_async`, `assistant_answer_async`, `retry_failed_ingestions` |
| **Events consumed** | `manual.ingestion_requested` (from `FILES`) |
| **Events emitted** | `ai.checklist_requested/completed/failed`, `ai.ingestion_completed/failed`, `ai.assistant_answered` |
| **Published ports** | `ChecklistGenerationService.generate(prompt, ctx)`, `AssistantService.ask(thread_id, question)`, `EmbeddingIndex.upsert/query` (used by MCP `ask_manual_assistant`) |
| **Internal deps** | `CORE`, `DB` (pgvector), `API`, `CACHE` (stricter AI rate limits), `WORKER`, `STORAGE` (manual bytes) |
| **Config** | `CMMS_AI__PROVIDER=openrouter|openai|anthropic|local`, `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `CHAT_MODEL`, `EMBEDDING_MODEL`, `TIMEOUT`, `MAX_RETRIES`, `PRIVACY_MODE_ORGS`, `RATE_LIMIT_AI_*` |
| **Health** | Adapter reachability probe (tiny completion / embedding ping), pgvector readiness, ingestion queue depth |
| **Swap procedure** | Implement `AIProviderAdapter` → drop file in `providers/` → set `CMMS_AI__PROVIDER`. **No other module changes.** Contract tests (§16) guarantee behavioral parity. |

---

# 9. `MCP` — External AI Operability Server

| Aspect | Detail |
|---|---|
| **Responsibilities** | Full MCP server per baseline §25: JSON-RPC 2.0 over **stdio + Streamable HTTP/SSE**; separate inbound surface (nginx `/mcp/*` → this service; never part of the REST app); authentication via JWT or scoped API key → bound to exactly one `organization_id` + one org role (MANAGER/REPORTER/OPERATOR/MAINTENANCE; **SYS_ADMIN never exposed**); exposes **resources** (read), **tools** (write), **prompts** (templates) exactly as enumerated in baseline §25.6–25.8; every call delegated to the **same published ports** REST uses — zero duplicated business logic. |
| **Mandatory guardrails** | Confirmation gates (STOP_UNTIL_COMPLETE flags, decommissions, large clones, CRITICAL tickets) returning `pending_confirmation` + token; `dry_run` on all write tools; per-tool rate limits (30 writes/min, 10 AI-assist/min); operation ceilings (50 WOs / 50 tickets per session-hour); no downgrading human-set safety flags (escalate-only); `batch_rollback` within 5-minute window if untouched by humans. |
| **Audit** | Every tool call logged via `AUDIT` with `actor_type=MCP_AGENT`, tool name, input hash, result — powering the org-level "AI Activity Log". |
| **Published ports** | Consumes: `AUTH.TokenService`, `TENANCY.*`, `ASSETS.*`, `CYCLES.*`, `TEMPLATES.*`, `WORKORDERS.*`, `TICKETS.*`, `REPORTS.KpiService`, `AI.ChecklistGenerationService`, `AI.AssistantService`, `CACHE.RateLimiter/LockService`. Publishes: nothing to other modules (leaf consumer). |
| **Internal deps** | `CORE` + all listed ports (declared dependencies; boot fails if any missing). |
| **Config** | `MCP_TRANSPORT=stdio|http`, `MCP_HTTP_PORT=8100`, `MCP_ALLOWED_ORIGINS`, `MCP_MAX_BATCH_SIZE=50`, `MCP_CONFIRMATION_REQUIRED=true`, `MCP_DRY_RUN_DEFAULT=false` |
| **Health** | Transport liveness, auth bridge self-test, quota-service connectivity |

---

# 10. Global Beat Schedule (contributed by modules, executed by `WORKER`)

| Task | Owning module | Cadence |
|---|---|---|
| `evaluate_due_cycles` | CYCLES | ~1 min |
| `detect_missed_cycles` | CYCLES | ~5 min |
| `flag_overdue_work_orders` | WORKORDERS | ~5 min |
| `resume_snoozed_work_orders` | WORKORDERS | ~1 min (+ delayed queue) |
| `expire_invitations` (14 d) | TENANCY | hourly |
| `expire_notifications` (30 d) | NOTIFY | daily |
| `refresh_metrics` | REPORTS | ~15 min |
| `retry_failed_ingestions` | AI | ~10 min |
| `sweep_expired_tokens` | AUTH | daily |

---

# 11. Domain Event Catalog (bus-mediated decoupling)

| Event | Producer | Key consumers |
|---|---|---|
| `cycle.due` | CYCLES | **WORKORDERS** (generate), NOTIFY |
| `cycle.missed` / `cycle.eval_failed` | CYCLES | NOTIFY, AUDIT |
| `work_order.generated/overdue/snooze_expired/…` | WORKORDERS | NOTIFY, AUDIT, REPORTS (metrics invalidation) |
| `ticket.*` (created→escalated→closed) | TICKETS | NOTIFY, AUDIT |
| `manual.ingestion_requested` | FILES | **AI** (ingest) |
| `ai.ingestion_completed/failed`, `ai.checklist_completed/failed` | AI | NOTIFY, AUDIT |
| `counter.logged/reset`, `safety_flag.changed` | ASSETS | AUDIT, asset state recompute |
| `export.ready` | REPORTS | NOTIFY |
| `invitation.sent/accepted/expired` | TENANCY | EMAIL (send), AUDIT |
| `mcp.tool_invoked` | MCP | AUDIT |

Rules: producers never know consumers; listeners failing ≠ publisher failing; audit-critical listeners use post-commit delivery.

---

# 12. Dependency Matrix (internal, hard deps)

| Module | Depends on |
|---|---|
| CORE | — |
| DB, CACHE, STORAGE, EMAIL | CORE |
| WORKER | CORE, CACHE |
| API | CORE |
| OBSERVABILITY | CORE, API |
| AUTH | CORE, DB, CACHE, EMAIL, API |
| TENANCY | CORE, DB, API, AUTH |
| AUDIT | CORE, DB |
| NOTIFY | CORE, DB, API, CACHE |
| ASSETS | CORE, DB, API, TENANCY, STORAGE, WORKER |
| TEMPLATES | CORE, DB, API |
| CYCLES | CORE, DB, API, ASSETS, TEMPLATES, WORKER, CACHE |
| WORKORDERS | CORE, DB, API, TEMPLATES, ASSETS, CACHE, FILES, WORKER |
| TICKETS | CORE, DB, API, ASSETS, TENANCY |
| FILES | CORE, DB, API, STORAGE, TENANCY |
| REPORTS | CORE, DB, API, WORKER, STORAGE |
| AI | CORE, DB, API, CACHE, WORKER, STORAGE |
| MCP | CORE, AUTH, TENANCY, ASSETS, CYCLES, TEMPLATES, WORKORDERS, TICKETS, REPORTS, AI, CACHE |

The graph is acyclic by construction; the one potential cycle (CYCLES ↔ WORKORDERS) is broken by the `cycle.due` event.

---

# 13. Table Ownership Map (each table owned by exactly one module)

| Module | Tables |
|---|---|
| AUTH | users, auth_refresh_tokens, email_verification_tokens, password_reset_tokens, roles |
| TENANCY | organizations, organization_custom_fields, user_organization_memberships, invitations, subscription_tiers, payment_states |
| ASSETS | zones, zone_custom_fields, systems, system_zone_links, sub_systems, service_points, asset_qr_codes, counters, counter_logs, safety_flags, spare_parts_placeholder, service_point_parts_placeholder |
| CYCLES | cycles, cycle_triggers, cycle_evaluations |
| TEMPLATES | workflows, workflow_items, checklist_templates, checklist_items |
| WORKORDERS | work_orders, work_order_items, work_order_item_measurements, work_order_comments, work_order_signatures, snooze_records, rejection_records |
| TICKETS | tickets, ticket_reports, ticket_feedbacks, ticket_assignments, ticket_events |
| NOTIFY | notifications |
| REPORTS | dashboard_metrics, report_exports |
| AUDIT | audit_logs |
| FILES | files, work_order_attachments (join semantics owned with WORKORDERS) |
| AI | document_ingestion_jobs, document_chunks (+embedding), ai_generation_jobs, ai_assistant_threads, ai_assistant_messages, ai_usage_logs |

---

# 14. Repository Structure

```
server/
├── core/                          # KERNEL — no CMMS logic
│   ├── app.py                     # bootstrap & profiles
│   ├── module.py                  # ModuleBase contract
│   ├── registry.py                # modules + services registry
│   ├── events.py                  # event bus (post-commit aware)
│   ├── config.py                  # settings composition
│   ├── health.py                  # HealthReport aggregation
│   ├── supervision.py             # monitor/restart loop
│   ├── logging.py
│   └── time.py
├── modules/
│   ├── db/            (service.py, rls.py, migrations_hook.py, health.py)
│   ├── cache/         (redis_client.py, ratelimit.py, locks.py, delay.py)
│   ├── storage/       (service.py, backends/{local,minio,s3}.py, keys.py)
│   ├── email/         (service.py, providers/{smtp,api}.py, templates/)
│   ├── worker/        (celery_app.py, registry.py, idempotency.py, retry.py)
│   ├── observability/ (health_routes.py, metrics.py, module_status.py)
│   ├── api/           (app_factory.py, middleware/, errors.py, pagination.py)
│   ├── auth/          (routes.py, service.py, rbac.py, tokens.py, passwords.py)
│   ├── tenancy/       (routes.py, orgs.py, tiers.py, payments.py, invitations.py, tasks.py)
│   ├── audit/         (listener.py, store.py, query.py)
│   ├── notify/        (routes.py, service.py, listeners.py, tasks.py)
│   ├── assets/        (routes.py, zones.py, systems.py, nodes.py, counters.py,
│   │                   qr.py, cloning.py, state_service.py, tasks.py, models.py)
│   ├── templates/     (routes.py, workflows.py, checklists.py, snapshot.py)
│   ├── cycles/        (routes.py, engine.py, triggers.py, tasks.py, scheduler.py)
│   ├── workorders/    (routes.py, machine.py, generation.py, snooze.py, tasks.py)
│   ├── tickets/       (routes.py, machine.py, loop_guard.py, pool.py)
│   ├── files/         (routes.py, service.py, policy.py)
│   ├── reports/       (routes.py, kpis.py, exports.py, tasks.py)
│   ├── ai/            (as detailed in §8)
│   └── mcp/           (server.py, transport_{stdio,http}.py, auth_bridge.py,
│                       tools/, resources/, prompts/, guardrails.py, rollback.py)
├── shared/                        # cross-module primitives ONLY
│   ├── enums.py                   # roles, statuses (mirrors baseline)
│   ├── events_catalog.py          # typed event names + payloads
│   ├── errors.py
│   └── ids.py
├── migrations/                    # Alembic, stamped per owning module
├── entrypoints/
│   ├── api.py  ├── worker.py  ├── beat.py  ├── mcp.py  └── all_in_one.py
├── tests/
│   ├── contracts/                 # adapter contract suites (storage/email/AI)
│   ├── unit/  ├── integration/  ├── isolation/  └── e2e/
└── docker/  (compose: api, worker, beat, mcp, db, redis, minio, nginx)
```

---

# 15. Configuration & Secrets

- All config via environment variables, namespaced: `CMMS_<MODULE>__<KEY>` (e.g., `CMMS_AI__PROVIDER=openrouter`, `CMMS_DB__POOL_SIZE=20`).
- Each module declares its settings schema; `core` validates all at boot and refuses to start on invalid/missing critical config.
- Secrets (`JWT_SECRET`, DB password, S3 keys, `OPENROUTER_API_KEY`, SMTP creds) only from environment/secret manager; redacted in logs; separate sets per dev/staging/prod.
- Feature flags: `CMMS_FEATURE_MCP=true`, `CMMS_AI__PRIVACY_MODE_ORGS=…` allow staged rollouts without code changes.

---

# 16. Key Data Flows

**A. Calendar cycle due → work order**
`beat → CYCLES.evaluate_due_cycles` (lock via CACHE) → trigger satisfied → emit `cycle.due` → `WORKORDERS` listener: `TEMPLATES.snapshot()` + create WO (idempotent key) → emit `work_order.generated` → `NOTIFY` alerts assignee; `AUDIT` records; `REPORTS` invalidates metrics.

**B. RAG question (REST or MCP — identical path)**
Request → `AI.AssistantService.ask` → retrieve pgvector chunks filtered by `organization_id + service_point_id` → `AIGateway` (OpenRouter adapter) → grounded answer + citations → `ai_usage_logs` → response (SSE stream optional).

**C. Operator raises a repair ticket**
`POST /tickets` → `TICKETS` → `TENANCY.PaymentStatusService.can_create_ticket` (overdue → standard 403) → create OPEN, route to pool → emit `ticket.created` → `NOTIFY` informs MAINTENANCE; loop-guard caps feedback cycles at 3 → escalation path.

**D. MCP dry-run zone clone**
External agent → `MCP` (HTTP/SSE, JWT) → role check (MANAGER) → guardrail: `dry_run=true` → `ASSETS.clone(plan_only=True)` → returns computed side-effects, nothing persisted; real execution of large clones requires confirmation token.

---

# 17. Swap / Upgrade Guide (the payoff of modularity)

| Change | What you touch | What stays untouched |
|---|---|---|
| OpenRouter → Azure OpenAI / Anthropic / local Ollama | New adapter in `modules/ai/providers/` + one env var | All CMMS modules, REST, MCP, UI |
| MinIO → AWS S3 or local disk | `STORAGE` backend + env var | FILES, REPORTS, AI |
| SMTP → SendGrid/SES | `EMAIL` provider adapter | AUTH, TENANCY |
| Redis → compatible broker | `CACHE` internals + `WORKER` broker config | Every module using RateLimiter/Lock ports |
| Polling → SSE notifications | `NOTIFY` delivery + `API` stream route | All producers (they only emit events) |
| Add a new MCP tool | Register tool in `MCP` wrapping an existing port | Domain modules |
| New report KPI | `REPORTS` only | Everything else |

CI enforces this: an **import-graph test** fails the build if any module imports another module's internals instead of declared ports.

---

# 18. Testing Strategy (per module layer)

1. **Adapter contract suites** — one abstract test battery run against every storage backend, email provider, and AI provider adapter (mocked LLM included), guaranteeing swap safety.
2. **Module unit tests** — state machines (WO, ticket loop guard), cycle trigger logic, quota math, snapshot semantics.
3. **Isolation tests** — cross-org access attempts return not-found/forbidden across REST *and* MCP; RAG retrieval never crosses org boundaries.
4. **Integration** — event-driven flows end-to-end (cycle→WO→notification→audit) inside a test compose stack.
5. **RBAC matrix tests** — every endpoint × every role (incl. deactivated users, overdue-org ticket block, tier limits).
6. **Boot tests** — core detects dependency cycles, missing ports, unhealthy modules before serving traffic.

---

# 19. Deployment Topology (server side only)

```
[Web UI server] ──┐
[Mobile PWA/App] ─┼─► [Cloudflare/WAF] ─► [Nginx]
[AI Orchestrator] ┘                         ├─ /api/*    → api      (FastAPI, core profile=api)
                                            ├─ /mcp/*    → mcp      (restricted network)
                                            └─ (no /static — UI is hosted elsewhere)
Internal: worker, beat, db (PostgreSQL+pgvector), redis, minio — as defined in baseline §24.
```

Health readiness gates the load balancer; `/health/ready` returns OK only when `core` reports all hard-dependency modules healthy.

---

# 20. Baseline Coverage Check

Every MVP capability in `architecture.txt` maps to exactly one owning module: auth §5→`AUTH`; orgs/tiers/payments/invitations §6→`TENANCY`; hierarchy/counters/QR/safety §7–8,10→`ASSETS`; cycles §9→`CYCLES`; templates/work orders §11→`TEMPLATES`+`WORKORDERS`; tickets §12→`TICKETS`; notifications §13→`NOTIFY`; reporting §14,23→`REPORTS`; files §15→`FILES`+`STORAGE`; API §17→`API`+owning modules; background §18→`WORKER`; AI §19→`AI`; audit §20→`AUDIT`; security §21→`API`/`AUTH`/`CACHE` middleware; frontend concerns §22 live on the **separate UI server** and are out of scope here; MCP §25→`MCP`; observability §26→`OBSERVABILITY`.

The MVP scope boundaries (exclusions: offline mode, IoT, vision AI, inventory, SSO/MFA, seasonal cycles, etc., baseline §29) are inherited unchanged — and thanks to the module system, each future capability is a **new module or a new adapter**, not a rewrite.

---

If you'd like, I can follow this up with (a) the concrete Python `core` kernel skeleton code, (b) per-module OpenAPI route tables, or (c) the Docker Compose + nginx routing configuration for the four processes.
