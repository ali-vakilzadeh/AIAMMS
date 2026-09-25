# AIAMMS – SOFTWARE ARCHITECTURE DOCUMENT (MVP)

| Item | Value |
|---|---|
| Document version | 2.0 |
| Date | 2026‑09‑25 |
| Conforms to | `requirements.md` v2.0 (scope), `project_specification.md` v2.0 (behaviour) |

This document describes **how** the system is built. Behavioural rules live in the specification and are referenced as `[spec §n]`. Requirements are referenced by ID (e.g. `[INV-005]`).

---

## 1. SYSTEM OVERVIEW

AIAMMS is a multi‑tenant, role‑based, open‑source CMMS delivered as a web SaaS and as a self‑hostable distribution. It is built as a **modular monolith**: one Python domain codebase serves the REST API, the MCP server, and background workers. A React SPA (installable as a PWA) is the only first‑party client.

Main capability areas:
- Identity
- Tenancy with sub‑organizations
- Locations & nested assets
- Meters
- Preventive maintenance engine
- Checklists / workflow engine
- Work orders
- Labour
- Tickets
- Reliability (failure codes, downtime)
- Inventory
- Purchasing
- Notifications
- Reporting
- Search
- Files
- AI copilot (generation, RAG, troubleshooting, auto‑fill)
- AI training‑data pipeline
- MCP server

---

## 2. ARCHITECTURAL DRIVERS

| Driver | Source | Architectural response |
|---|---|---|
| Hard tenant isolation incl. sibling sub‑orgs | ORG-005, ORG-008 | `tenant_id` + `org_unit_id` on every row; PostgreSQL RLS; single policy layer shared by REST and MCP (§6) |
| Safety‑relevant correctness (no duplicate/missed PM, safety states) | PM-018, SAF-* | DB uniqueness constraints, advisory locks, state computed from explicit causes (§11–12) |
| Inventory correctness under concurrency | INV-005, INV-008 | Append‑only ledger + locked balance projection in one transaction (§14) |
| Persian/English, RTL, Jalali | I18N-* | Calendar‑aware recurrence engine; shared normalization rules; ICU i18n (§8) |
| AI never acts without approval; privacy | AI-001, AI-012, AIT-* | AI drafts as first‑class entities; sanitizer; separate training store (§19–20) |
| External agents operate safely | MCP-* | Command bus with dry‑run, confirmation gates, compensations (§21) |
| One codebase for SaaS and self‑hosting | COM-002, NFR-016 | Feature flags; Compose and Helm deployments (§26) |
| Scale targets | NFR-003, NFR-004 | Indexed `next_due_at`, partitioned high‑volume tables, horizontal workers (§27) |

---

## 3. TECHNOLOGY STACK (DECIDED)

| Layer | Choice | Notes |
|---|---|---|
| Frontend | React 18+, TypeScript, Vite | SPA + PWA |
| UI styling | Tailwind CSS with logical properties (`ms-*`, `pe-*`, `start-*`) | RTL/LTR mirroring |
| Server state | TanStack Query | polling, cache invalidation |
| Forms / validation | react-hook-form + zod | zod schemas generated from OpenAPI |
| Tables | TanStack Table | virtualized lists |
| Workflow graph editor | React Flow | M4 |
| i18n | i18next + ICU MessageFormat | fa / en bundles |
| Dates | dayjs + `jalaliday` plugin (or date-fns-jalali) | Jalali/Gregorian display and pickers |
| Charts | Apache ECharts | RTL‑aware |
| PWA / offline | Workbox service worker, IndexedDB via Dexie | MOB-005 |
| QR/barcode scanning | `@zxing/browser` | QR + Code128 |
| Signature capture | signature_pad | |
| Fonts | Vazirmatn (fa), Inter (en) | self‑hosted |
| Backend | Python 3.11+, **FastAPI**, Pydantic v2, SQLAlchemy 2 (async), Alembic | |
| Jalali (backend) | `jdatetime` | wrapped by own calendar module |
| Workers | Celery 5 + Redis broker; Celery Beat | multiple queues |
| Database | PostgreSQL 15+ with `pgvector`, `ltree`, `pg_trgm`, `unaccent` | |
| Cache / locks / rate limits | Redis 7+ | |
| Object storage | MinIO / any S3‑compatible; local FS adapter for dev | |
| PDF | WeasyPrint (HTML → PDF, supports RTL with Vazirmatn) | reports, PO, labels |
| XLSX | openpyxl | import/export |
| QR generation | `segno` | SVG/PNG |
| Document extraction | pypdf / pdfplumber, python-docx; Tesseract OCR (`fas` + `eng`) | RAG ingestion |
| Embeddings | Self‑hosted multilingual model (default **BAAI/bge‑m3**, 1024‑d) via a small embedding service; provider option for hosted embeddings | Persian support; manuals never leave the platform unless configured |
| LLM | Provider abstraction: OpenAI‑compatible, Anthropic, Ollama / vLLM | |
| NER for anonymization | multilingual NER model (fa + en), run in the training worker | AIT-003 |
| Antivirus | ClamAV (clamd) | SEC-005 |
| MCP | Official MCP Python SDK; stdio + Streamable HTTP | |
| Email | SMTP or provider API behind an abstraction | auth, scheduled reports, PO |
| Reverse proxy | Nginx | TLS, static, routing |
| CI/CD | GitHub Actions | |
| Error tracking | Sentry‑compatible SDK | |
| Container / orchestration | Docker, Docker Compose, Helm chart for Kubernetes | |

---

## 4. COMPONENT MODEL

```
                    ┌──────────────────────────────┐
  Browser / PWA ───▶│ Nginx (TLS, static, routing) │◀─── External AI agents (MCP over HTTP)
                    └──────┬───────────────┬───────┘
                           │/api           │/mcp
                  ┌────────▼──────┐  ┌─────▼────────┐
                  │  API (FastAPI)│  │  MCP server  │
                  └────────┬──────┘  └─────┬────────┘
                           │  shared domain package (aiamms.domain)
      ┌────────────────────┼───────────────┴─────────────┬──────────────────┐
      ▼                    ▼                             ▼                  ▼
 PostgreSQL          Redis (broker, cache,         Object storage     Celery workers
 (+pgvector,         locks, rate limits)           (MinIO/S3)         (queues below)
  ltree, trgm)                                                        + Celery Beat
                                                                           │
                             ┌────────────────┬───────────────┬────────────┴──────┐
                             ▼                ▼               ▼                   ▼
                      Embedding service   LLM providers    ClamAV            SMTP / email API
                      (bge-m3)            (ext / Ollama)
```

| Component | Responsibility |
|---|---|
| **SPA / PWA** | All UI; offline queue; QR scanning; i18n; talks only to `/api`. |
| **API** | Stateless REST `/api/v1`: authentication, request validation, policy enforcement, invocation of domain commands and queries, OpenAPI. |
| **MCP server** | Separate process; authenticates API keys/JWT; maps MCP tools/resources onto the same domain commands/queries (§21). |
| **Domain package** | Entities, commands, queries, policies, domain events. No FastAPI or MCP imports. |
| **Workers** | Queues: `scheduler` (cycle evaluation), `default` (notifications, outbox), `inventory` (reorder checks, reconciliation), `files` (scan, thumbnails), `ingestion` (RAG), `ai` (generation, troubleshooting), `reports` (exports, PDFs, scheduled reports), `imports`, `training` (anonymization pipeline; isolated credentials). |
| **Beat** | Periodic triggers (§17). |
| **PostgreSQL** | System of record, vectors, full‑text search, audit. |
| **Redis** | Broker, rate limits, short caches (membership cache ≤ 60 s), distributed locks, AI quota counters. |
| **Object storage** | Files, manuals, thumbnails, exports, PDFs, import files, training datasets (separate bucket). |
| **Embedding service** | Stateless HTTP service hosting the embedding model (CPU acceptable for MVP load; GPU optional). |
| **ClamAV** | Upload scanning. |
| **Account Management Service (AMS)** | Separate, isolated service (own DB and keys) that owns plans, payments, and account policies. The CMMS only consumes signed + encrypted **entitlements** from it (§6.8, `account_management_service.md`). Replaced by a static adapter in the self‑hosted edition. |
| **Notification providers** | External delivery channels behind adapters: SMTP/email API, Web Push (VAPID), SMS gateways, mobile push, webhooks, or one external notification server (§16). |

---

## 5. CODE ORGANIZATION

```
backend/
  aiamms/
    core/            # config, db session, RLS context, i18n, calendar, normalization, errors, ids
    domain/
      identity/  tenancy/  rbac/  locations/  systems/  assets/  meters/
      cycles/  templates/  workflow_engine/  work_orders/  labour/  tickets/
      reliability/  safety/  inventory/  purchasing/  notifications/  reporting/
      search/  files/  imports/  onboarding/  ai/  ai_training/  audit/  mcp_support/
      (each: models.py, commands.py, queries.py, policies.py, events.py, schemas.py)
    api/             # FastAPI routers (thin)
    mcp/             # MCP server (thin)
    workers/         # Celery tasks (thin)
  migrations/        # Alembic
frontend/
  src/ app/ modules/<same domains>/ components/ i18n/{fa,en}/ offline/ lib/calendar/
shared/
  normalization-test-vectors.json   # Persian normalization, shared by Python & TS tests
  recurrence-test-vectors.json      # Jalali/Gregorian recurrence cases
```

**Command pattern:** every state change is a `Command` object:
1. Validated with Pydantic.
2. Authorized by a policy.
3. Executed in a DB transaction.
4. Emits domain events to an outbox.

This one mechanism gives:
- **Audit:** every command produces an audit entry.
- **Idempotency:** commands carry an optional `idempotency_key` (used by offline sync and MCP).
- **Dry‑run:** execute, then roll back.
- **Undo:** commands declare a compensating command, used by MCP undo.

---

## 6. MULTI‑TENANCY & ORG UNITS

### 6.1 Data keys
- Every tenant‑owned table has `tenant_id` (root org) and `org_unit_id` (owner unit).
- `org_units` stores `path ltree` (e.g. `root.plantA.lineB`), depth ≤ 3 (CHECK on `nlevel(path)`).

### 6.2 Request context
The API resolves, per request:
- `tenant_id` of the user,
- `active_org_unit_id` (header `X-Org-Unit`, validated),
- effective role in that unit [spec §3.2],
- zone scope,
- the **readable org unit set** (the active unit, plus descendants when "include sub‑orgs" is requested and inherited access exists).

It then sets PostgreSQL session settings inside the transaction:
```sql
SET LOCAL app.tenant_id = '<uuid>';
SET LOCAL app.org_unit_ids = '{<uuid>,<uuid>}';
SET LOCAL app.actor = '<user|key id>';
```

### 6.3 Row‑Level Security
Every tenant table has:
```sql
ALTER TABLE x ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON x
  USING (tenant_id = current_setting('app.tenant_id')::uuid
         AND org_unit_id = ANY (current_setting('app.org_unit_ids')::uuid[]));
```
- The application connects as role `app_user` (no BYPASSRLS).
- Migrations run as `app_owner`.
- Background workers set the context per job (tenant + unit set taken from the job payload).
- Jobs that iterate across tenants (e.g. the scheduler dispatcher) use a restricted `app_scheduler` role. It can read only scheduling columns cross‑tenant, then sets the context before doing any work.

### 6.4 Zone scope
Zone scope is enforced in the **query layer**, not by RLS:
- Every repository query for zone‑bound entities joins/filters by `zone_path <@ ANY(scope_paths)`.
- A test suite asserts that every zone‑bound query uses the scoped repository.

### 6.5 Consolidated views
[spec §3.3] Aggregate queries run through a dedicated `ConsolidatedReportingService`:
- It sets `app.org_unit_ids` to the descendant set.
- It returns only grouped aggregates. Its result schemas have no record‑level fields.
- Drill‑down links are rendered only for units where the user has effective access.

### 6.6 Platform administration
- SYS_ADMIN endpoints live under `/api/v1/admin`. They are served by the same API but require a platform role.
- Tenant data access requires an active **support session** record (reason, expiry). While it is active, the context is set to that tenant. All queries are audited with the support session ID [RBAC-007].

### 6.7 Storage isolation
Object keys are prefixed by tenant and org unit: `t/{tenant_id}/u/{org_unit_id}/{purpose}/{yyyy}/{mm}/{file_id}`. The API only issues pre‑signed URLs after a policy check. Buckets are private.

### 6.8 Entitlements & tier enforcement
- **Commercial logic lives outside the CMMS** in the Account Management Service (AMS). Full design and messaging protocol: `docs/account_management_service.md`.
- The CMMS `commercial` package holds an `EntitlementPort` with two adapters: `remote` (HTTPS, sign‑then‑encrypt JOSE messages) and `static` (self‑hosted/dev; fixed ENTERPRISE entitlement). Selected by `AMS_MODE`.
- Entitlements (`plan`, `status`, `limits`, `features`, `blocked_actions`, `valid_until`, `grace_until`, `revision`) are cached in `tenant_entitlements`. **Enforcement reads only this cache**; no request ever waits on the AMS.
- The CMMS never branches on the plan name. `EntitlementGuard` enforces limit keys (e.g. `assets.active.max`), feature keys (e.g. `mcp.write`), and status effects [COM‑008].
- `EntitlementGuard.check_limit("assets.active.max", tenant, org_unit, n)` counts in‑scope assets using a maintained counter table (`tenant_asset_counts`, updated transactionally by asset lifecycle commands), with a nightly recount. Sub‑org quota allocations [COM‑005] stay in the CMMS.
- Refresh: AMS push (`entitlement.changed`) + scheduled refresh + nightly reconcile. If the AMS is unreachable, the cached entitlement is used until `grace_until`, then `AMS_STALE_POLICY` applies. Reads and exports are never blocked.
- MVP: the AMS is a protocol‑complete stub that returns ENTERPRISE (unlimited) for every tenant.

---

## 7. AUTHENTICATION & AUTHORIZATION

- **Tokens** [spec §2.2]:
  - Access JWT (EdDSA signed, 15 min).
  - Refresh token: opaque random value, stored hashed, with a family ID for reuse detection.
  - Sessions table: device, IP, last used.
- **Password hashing:** Argon2id (`argon2-cffi`).
- **Policy layer:**
  - `rbac/permissions.py` defines permission constants and the role → permission map. It is the executable form of spec §4.
  - Object‑level checks (◐ rules: "assigned only", "issuer only") are policy functions per command.
  - REST and MCP call the same `authorize(actor, command)`.
- **Membership cache:** Redis, 60 s TTL, invalidated on membership change events.
- **Rate limiting:** Redis sliding window per user, IP, API key, and endpoint class [SEC-003].
- **CSRF:** the refresh endpoint uses a SameSite=Strict cookie + double‑submit token. All other endpoints use Bearer tokens.

---

## 8. LOCALIZATION ARCHITECTURE

- **Frontend:**
  - i18next namespaces per module. ICU plurals and gender‑neutral messages.
  - `dir` is set on `<html>` from the user's language. Tailwind logical utilities only (a lint rule forbids `ml-`/`mr-`/`left-`/`right-`).
  - Icons with direction (arrows, chevrons) use mirrored variants in RTL.
- **Calendar module (shared semantics):**
  - Python `aiamms.core.calendar` and TS `lib/calendar` expose the same functions: `to_display`, `parse_input`, `add_months(calendar, ...)`, `month_length`, `next_occurrence(rule, after, tz)`.
  - Both are tested against `shared/recurrence-test-vectors.json`.
- **Normalization:**
  - `normalize_text()` in Python/TS, and SQL function `norm_fa(text)` (IMMUTABLE, built on `translate()` + `regexp_replace`).
  - All three implement spec §5.2 and are tested against shared vectors.
  - Search columns are generated as `norm_fa(name_fa || ' ' || name_en || ...)`.
- **Backend messages:**
  - Babel/gettext catalogues for emails, PDFs, export headers, and notification templates.
  - Notifications store `title_key` + params and are rendered at read time in the reader's language.
- **Bilingual fields** are stored as JSONB `{fa, en}`, with a generated column `name_search = norm_fa(coalesce(name->>'fa','') || ' ' || coalesce(name->>'en',''))`.
- **Numbers/currency:** `Intl.NumberFormat('fa-IR' | 'en-US')`. Toman display = Rial / 10, as a presentation option only.
- **PDF:** WeasyPrint templates with `dir="rtl"`, Vazirmatn embedded, Jalali dates.

---

## 9. DATA ARCHITECTURE

### 9.1 Principles
- UUID v7 primary keys (time‑ordered).
- Standard columns: `tenant_id, org_unit_id, created_at, created_by, updated_at, updated_by, deleted_at, version`.
- Timestamps `timestamptz` (UTC). Business dates `date` + org unit timezone.
- Money `numeric(20,4)`, quantities `numeric(18,4)`.
- Custom/spec fields in JSONB, validated against per‑org definitions.
- Partial unique indexes ignore soft‑deleted rows: `UNIQUE (org_unit_id, code) WHERE deleted_at IS NULL`.
- High‑volume append tables are range‑partitioned by month: `stock_ledger`, `meter_readings`, `audit_logs`, `notifications`, `ai_interactions`, `outbox`.

### 9.2 Hierarchies
| Tree | Storage | Limits enforced by |
|---|---|---|
| Org units | `parent_id` + `path ltree` | CHECK `nlevel(path) <= 3` |
| Zones | `parent_id` + `path ltree` | CHECK `nlevel(path) <= 3` |
| Systems | `parent_id` (1 level) | CHECK via trigger |
| Assets | `parent_asset_id` + `path ltree` | trigger: depth ≤ 4, no cycles, same org unit, zone equals parent's zone |

The asset `path` is maintained by the move command, which updates the whole subtree (`path`, `zone_id`) in one statement. `zone_path` is denormalized onto assets for scope filtering.

### 9.3 Core entities (selected columns)

**Assets & locations**
```
zones(id, org_unit_id, parent_id, path, code, name jsonb, status, address jsonb, contact jsonb,
      geo point, custom jsonb)
systems(id, org_unit_id, parent_id, code, name jsonb, classification_id, criticality, spec jsonb, status)
system_zone_links(system_id, zone_id, is_primary)
asset_classes(id, org_unit_id, parent_id, code, name jsonb, spec_schema jsonb, default_meters jsonb,
              default_criticality)
assets(id, org_unit_id, code, name jsonb, asset_class_id, zone_id, zone_path, position_text,
       system_id, parent_asset_id, path, manufacturer, model, serial_number, year, install_date,
       purchase_date, purchase_cost, vendor_id, warranty_expiry, criticality, priority,
       lifecycle_status, operating_state, spec jsonb, qr_token UNIQUE, rotable_serial_id,
       is_sample)
asset_events(id, asset_id, type, from jsonb, to jsonb, reason, actor, at)   -- moves, installs, lifecycle
asset_bom_lines(id, owner_type ASSET|CLASS, owner_id, part_id, qty, uom_id, note, hides_line_id)
```

**Meters**
```
meters(id, asset_id, type, unit, name, rollover_value, max_rate_per_day, derived_from_meter_id,
       derived_offset, lifetime_value, last_reading_at)
meter_readings(id, meter_id, reading_at, value, delta, lifetime_after, source, entered_by,
               suspicious, voided_at, void_reason, segment_no)            -- partitioned
meter_segments(meter_id, segment_no, start_value, end_value, replaced_at)
```

**Cycles**
```
cycles(id, org_unit_id, code, name, target_type, target_id, scope_mode, class_filter uuid[],
       template_family_id, template_version_id, follow_latest, work_type, priority, safety_flag,
       safety_propagation, est_duration, planned_parts jsonb, planned_crafts jsonb, assignee jsonb,
       scheduling_basis, lead_time interval, lead_units numeric, grace interval, deadline_behavior,
       launch_mode, launch_slots time[], non_working_day_rule, open_wo_policy, influence_children,
       nesting_group_id, nesting_rank, status)
cycle_triggers(id, cycle_id, type, rule jsonb)        -- recurrence rule / meter spec / season window
cycle_instances(id, cycle_id, asset_id NULL, target_type, target_id, enabled, overrides jsonb,
                next_due_at timestamptz, next_due_trigger_id, calendar_anchor timestamptz,
                last_wo_id, last_completed_at)
cycle_instance_baselines(cycle_instance_id, trigger_id, meter_id, baseline_value)
cycle_evaluations(id, cycle_instance_id, due_point timestamptz, trigger_id, result, wo_id, at, error)
  UNIQUE (cycle_instance_id, due_point) WHERE result = 'GENERATED'
```
Index: `cycle_instances(next_due_at) WHERE enabled` (with a partial filter on active cycles).

**Templates & workflow**
```
template_families(id, org_unit_id, code, name, type, class_hints uuid[], shared_to_sub_orgs)
template_versions(id, family_id, number, state, change_note, published_at, published_by,
                  ai_draft_id, graph_hash)
template_nodes(id, version_id, activity_no, node_type, description jsonb, instructions jsonb,
               measurement jsonb, est_duration, crafts jsonb, certifications jsonb, tools jsonb,
               parts jsonb, safety_flag, permit jsonb, risk, signature_required, allow_na, on_fail,
               location_override jsonb, search_text)
template_edges(version_id, from_node_id, to_node_id, condition_ast jsonb, condition_text,
               branch_order, is_else)
```

**Work orders**
```
work_orders(id, org_unit_id, number, work_type, source, cycle_instance_id, due_point, ticket_id,
            parent_wo_id, target_type, target_id, zone_path, title jsonb, description,
            template_version_id, priority, safety_flag, issued_at, planned_start, due_at,
            started_at, completed_at, closed_at, stopped_at, status, prev_status, outcome,
            lead_user_id, team_id, role_pool, hold_reason, snooze_until, snooze_reason,
            qc_required, qc_reviewer_id, qc_result, acknowledged_by, acknowledged_at,
            overdue_on_creation, cost_labour, cost_parts, cost_external, failure_problem_id,
            failure_cause_id, failure_action_id, version)
wo_assignees(wo_id, user_id, is_lead)
wo_nodes(id, wo_id, source_node_id, activity_no, node_type, snapshot jsonb, status, result,
         measurement_value jsonb, auto_result, override_reason, performed_by, started_at,
         completed_at, comment, signature_id, permit jsonb, assigned_to jsonb, downtime_impact)
wo_edges(wo_id, from_wo_node_id, to_wo_node_id, condition_ast, is_else, branch_order)
signatures(id, entity_type, entity_id, user_id, full_name, role, image_file_id, content_sha256,
           ip, signed_at)
labour_entries(id, wo_id NULL, ticket_id NULL, user_id, craft_id, start_at, end_at, hours,
               type, rate, multiplier, cost)
external_costs(id, wo_id, vendor_id, description, amount, po_line_id)
```

**Tickets & reliability**
```
tickets(id, org_unit_id, number, target_type, target_id, zone_path, title, description, priority,
        symptom_problem_id, asset_stopped, issuer_id, status, loop_count, extra_loop_used,
        assignee_id, claimed_at, first_response_at, linked_wo_id, sla_response_due,
        sla_resolution_due, sla_paused_seconds, response_breached, resolution_breached,
        resolution_type, closed_at)
ticket_reports(id, ticket_id, loop_no, work_done, failure codes, submitted_by, submitted_at,
               from_wo_id)
ticket_feedbacks(id, ticket_id, loop_no, text, by, at, on_behalf)
failure_codes(id, org_unit_id, level PROBLEM|CAUSE|ACTION, code, name jsonb, parent_ids uuid[],
              class_ids uuid[], active)
downtime_events(id, asset_id, start_at, end_at, type, reason_id, source, wo_id, ticket_id,
                state_cause_id)
asset_state_causes(id, asset_id, cause_type, origin_asset_id, wo_id, ticket_id, effect_state,
                   created_by_actor_type, created_at, cleared_at, cleared_by, clear_reason)
```

**Inventory**
```
uoms(id, org_unit_id, code, name jsonb)
parts(id, org_unit_id, part_no, name jsonb, description, category_id, stock_uom_id,
      purchase_uom_id, purchase_factor, manufacturer, mfr_part_no, stocked, tracking,
      shelf_life_days, criticality, barcode, rotable, status, abc_class)
part_alternates(part_id, alternate_part_id, two_way)
storerooms(id, org_unit_id, zone_id, code, name, type, self_issue_allowed, allow_negative)
bins(id, storeroom_id, code, description)
lots(id, part_id, lot_no, expiry)
serials(id, part_id, serial_no, status, current_storeroom_id, current_bin_id, asset_id)
stock_balances(part_id, storeroom_id, bin_id, lot_id NULL, serial_id NULL, on_hand)
  PK (part_id, storeroom_id, bin_id, coalesce(lot_id), coalesce(serial_id))
stock_reservations(id, wo_id, part_id, storeroom_id, qty, released_qty, status)
part_costs(part_id, org_unit_id, avg_cost, updated_at)
stock_ledger(id, org_unit_id, posted_at, type, part_id, storeroom_id, bin_id, lot_id, serial_id,
             qty, unit_cost, value, on_hand_after, ref_type, ref_id, ref_line_id, reason_code,
             reversal_of, actor)                                        -- partitioned, append-only
reorder_policies(part_id, storeroom_id, method, min, max, reorder_point, reorder_qty,
                 lead_time_days, safety_stock)
stock_alerts(id, part_id, storeroom_id, type, opened_at, resolved_at)
count_sheets(id, storeroom_id, number, state, blind, snapshot_at, approved_by)
count_lines(id, sheet_id, part_id, bin_id, lot_id, serial_id, expected_qty, counted_qty,
            variance_qty, variance_value)
```

**Purchasing**
```
vendors(id, org_unit_id, code, name jsonb, contacts jsonb, address jsonb, tax_id, payment_terms,
        lead_time_days, status, rating)
vendor_parts(vendor_id, part_id, vendor_part_no, price, purchase_uom_id, moq, lead_time_days,
             preferred)
requisitions(id, org_unit_id, number, state, requested_by, approved_by, ...)
requisition_lines(id, requisition_id, part_id NULL, description, qty, uom_id, required_date,
                  dest_storeroom_id, dest_wo_id, suggested_vendor_id, est_price, po_line_id)
purchase_orders(id, org_unit_id, number, vendor_id, state, order_date, expected_date,
                storeroom_id, payment_terms, discount_pct, tax_pct, subtotal, total,
                created_by, approved_by, approved_at, sent_at, version)
po_lines(id, po_id, line_no, part_id NULL, description, vendor_part_no, qty, uom_id, unit_price,
         discount_pct, dest_storeroom_id, dest_bin_id, dest_wo_id, required_date,
         received_qty, returned_qty, closed)
receipts(id, org_unit_id, number, po_id, received_at, received_by, delivery_note, reversed_by)
receipt_lines(id, receipt_id, po_line_id, qty, bin_id, lot_no, expiry, serial_nos text[],
              ledger_id)
```

**Other**
```
notifications(...)            -- partitioned
announcements(...), announcement_acks(...)
files(id, tenant_id, org_unit_id, storage_key, original_name, mime, size, sha256, purpose,
      scan_status, thumbnail_key, preview_key, uploaded_by)
documents(id, file_id, doc_type, title jsonb, language, ingestion_status, ingestion_error,
          page_count)
document_links(document_id, entity_type, entity_id)
document_chunks(id, tenant_id, org_unit_id, document_id, page_from, page_to, chunk_no, heading,
                text, text_norm tsvector, token_count, embedding vector(1024),
                embedding_model)
ai_drafts(...), ai_interactions(...)        -- see §19
mcp_api_keys(...), mcp_pending_actions(...), mcp_operations(...)  -- see §21
jobs(id, tenant_id, org_unit_id, user_id, type, status, progress, result_file_id, error,
     created_at, finished_at)
number_sequences(org_unit_id, doc_type, year, calendar, next_value)  -- row-locked increment
outbox(id, tenant_id, event_type, payload jsonb, created_at, processed_at)   -- partitioned
audit_logs(id, tenant_id, org_unit_id, at, actor_type, actor_id, actor_role, action, entity_type,
           entity_id, before jsonb, after jsonb, ip, user_agent, request_id, support_session_id,
           prev_hash, hash)                                                  -- partitioned
```

---

## 10. CYCLE ENGINE (PREVENTIVE MAINTENANCE)

### 10.1 Recurrence engine
- `aiamms.core.calendar.recurrence` implements spec §10.3. `next_occurrence(rule, after_local, tz)` iterates in the rule's calendar (Jalali via `jdatetime`), clamps missing month days to the month's end, applies the time of day in the org unit timezone, converts to UTC, and then applies the non‑working‑day rule using the work calendar.
- Precomputation: `cycle_instances.next_due_at` always stores the next due point in UTC. It is recomputed whenever the anchor, rule, override, suspension, or completion changes.

### 10.2 Evaluation flow
1. **Beat (every minute)** runs `dispatch_launch_slots`. It finds org units with a launch slot in the current minute (computed from each unit's timezone). For each unit it enqueues `evaluate_org_unit(org_unit_id, slot)` on the `scheduler` queue.
2. `evaluate_org_unit` selects candidate instances:
   - calendar/seasonal: `next_due_at - lead_time <= now()`;
   - meter: instances flagged `meter_dirty`.
3. For each instance, it takes a Postgres **advisory lock** on the instance ID, then:
   1. Re‑checks the state.
   2. Determines the winning trigger.
   3. Applies suppression (nesting group).
   4. Applies the open‑WO policy.
   5. Creates the WO snapshot plus reservations.
   6. Inserts the `cycle_evaluations` row.
   7. Writes outbox events.

   All of this happens in one transaction. The unique index on `(cycle_instance_id, due_point)` is the final duplicate guard [PM-018].
4. **Meter readings:** the reading command marks the affected instances `meter_dirty` and enqueues `evaluate_instances(ids)` immediately (AUTOMATIC mode).
5. **Missed detection:** when `next_due_at` is more than one period in the past, the engine walks the occurrences, writing `MISSED` rows for all but the latest [spec §10.10].
6. **Manual launch mode:** evaluation writes a `DUE_FOR_LAUNCH` state on the instance instead of generating a WO. The "Due for launch" list queries these.
7. **Deadline watcher (every 5 min):** WOs whose `due_at` has passed and whose cycle has FLAG_CRITICAL_STOP get a `DEADLINE_STOP` state cause, and an overdue notification is sent (once, tracked by a flag).

### 10.3 Scale
- The candidate query is index‑only on `next_due_at`. Evaluation is batched (500 instances per task).
- `scheduler` workers scale horizontally. Advisory locks make parallel workers safe.
- Target: 100k instances < 10 min [NFR-004].

### 10.4 Instance maintenance
Domain events (`AssetCreated`, `AssetMoved`, `AssetLifecycleChanged`, `CycleChanged`) trigger `sync_cycle_instances(cycle_id | asset_id)`, which creates, enables, or disables instances for EACH_DESCENDANT cycles.

---

## 11. WORKFLOW ENGINE

- A **template version** is stored as nodes and edges. On WO creation, nodes and edges are copied into `wo_nodes`/`wo_edges` (the snapshot) [WO-004].
- **Condition compilation:** `condition_text` is parsed by a small hand‑written parser (grammar in spec §12.3) into a JSON AST, stored in `condition_ast`. At runtime only the AST is interpreted. Nothing is ever passed to `eval`.
- **Runtime:**
  - A pure function `advance(wo_graph, event) -> state changes` runs after every item status change, inside the command transaction.
  - It marks successors READY when all predecessors are terminal (AND_JOIN) or when any incoming branch arrives (MERGE).
  - DECISION nodes are evaluated immediately when their inputs complete. Untaken branches become SKIPPED transitively.
  - `on_fail = STOP_WORKFLOW` short‑circuits: all non‑terminal nodes become SKIPPED.
- **Validation on publish:** a graph validator implements the spec §12.3 rules (topological sort, split/join matching via dominator analysis, ELSE presence, reference reachability).
- **Auto pass/fail** is computed in the item update command [WF-010].

---

## 12. SAFETY & OPERATING STATE SERVICE

- `asset_state_causes` holds active causes [spec §11.1]. `SafetyService.recompute(asset_ids)`:
  1. Collects the affected assets plus all ancestors (via `path`).
  2. Computes the effective state for each by precedence.
  3. Updates `assets.operating_state`.
  4. Opens and closes `downtime_events` on transitions.
  5. Emits `OperatingStateChanged` events (notifications, system "impaired" cache).
- It is called within the same transaction as the triggering command (WO start/complete/cancel, deadline watcher, manual state change, ticket with `asset_stopped`).
- Override and clear require the MANAGER permission. The MCP actor type cannot clear causes with `created_by_actor_type = USER` [MCP-008].

---

## 13. WORK ORDER, TICKET & LABOUR SERVICES

- **State machines** are declared as transition tables in code (`work_orders/state_machine.py`, `tickets/state_machine.py`), mirroring spec §13.2 and §15.2. Commands reject undeclared transitions with `INVALID_TRANSITION`.
- **Numbering:** `NumberingService.next(org_unit, doc_type, date)` performs a row‑locked increment on `number_sequences` inside the business transaction, so numbers are gap‑free except for rollbacks.
- **Acknowledgement:** the WO GET endpoint, for an assignee, issues an idempotent `AcknowledgeWorkOrder` command. It is an asynchronous fire‑and‑forget call from the client after the view, so GET stays safe.
- **Snooze expiry:** Celery `eta` task scheduled at `snooze_until`, plus a 5‑minute sweeper as a safety net.
- **SLA timers:** due timestamps are computed with the working‑calendar service at creation or on priority change. A 5‑minute sweeper flags breaches. Pause time is accumulated while in REPORT_SUBMITTED.
- **Ticket ↔ WO:** a `WorkOrderCompleted` event handler submits the ticket report for linked tickets.
- **Cost roll‑up:** WO cost columns are updated by labour, ledger, and external‑cost commands in the same transaction. Asset roll‑ups are queries over WOs (with `path` for components).

---

## 14. INVENTORY ENGINE

### 14.1 Posting service
`InventoryPostingService.post(transactions[])` is the **only** writer of `stock_ledger` and `stock_balances`:
1. Sort the affected balance keys deterministically (part, storeroom, bin, lot, serial) and `SELECT … FOR UPDATE` them. Missing rows are inserted with `ON CONFLICT DO NOTHING`, then locked.
2. For RECEIPT, lock `part_costs(part, org_unit)` and compute the new moving average [spec §17.5].
3. Validate the negative‑stock rule [INV-008], serial uniqueness, and lot expiry.
4. Insert ledger rows (with `on_hand_after`), update balances, and update reservation `released_qty` and PO line `received_qty` as applicable.
5. Emit `StockPosted` events. The handler enqueues a reorder evaluation for the affected (part, storeroom).

Lock ordering prevents deadlocks. Transactions run at READ COMMITTED with explicit row locks.

### 14.2 Reconciliation
A nightly job (`inventory` queue) recomputes `Σ ledger.qty` per balance key and compares it with `stock_balances`. Mismatches raise a platform alert and a tenant audit entry [INV acceptance].

### 14.3 Reservations & availability
- `available = Σ on_hand − Σ open reservations (qty − released_qty)` per (part, storeroom). It is served from a view.
- `on_order` is served from open `po_lines`.

### 14.4 Reorder evaluation
- Event‑driven plus nightly. Opens or resolves `stock_alerts`.
- The suggestion list is a query over policies, availability, and on‑order.

---

## 15. PURCHASING SERVICE

- PR/PO/receipt commands implement spec §18 state tables.
- **Approval routing:** `ApprovalPolicy.approver_scope(po)` compares the total with `po_approval_limit` of the unit and walks up the org tree.
- **Segregation‑of‑duties check:** configurable per tenant.
- **PO PDF:** WeasyPrint template in the PO language. "Send" optionally emails the vendor through the email abstraction and stores the sent PDF as a file.
- **Receipt:** builds RECEIPT transactions (stock lines) or WO external‑cost entries (direct lines) and calls the posting service. `PartsReceivedForWorkOrder` events trigger ON_HOLD resumption hints.

---

## 16. NOTIFICATIONS & EVENTS

- **Transactional outbox:** domain commands insert events into `outbox` in the same transaction. The `outbox_dispatcher` (default queue, every 2 s plus LISTEN/NOTIFY wake‑up) fans events out to handlers:
  - notification creation (recipient resolution per spec §19.2)
  - search index updates
  - web push
  - SSE broadcast
  - AI triggers (e.g. troubleshooting on ticket creation)
  - reorder checks
- Handlers are idempotent, keyed by event ID.
- **In‑app delivery:** `GET /notifications` polling (30 s) plus an optional SSE stream `/api/v1/notifications/stream`.
- **Retention:** notifications are partitioned monthly. Partitions older than 30 days are archived or dropped by Beat.

### 16.1 Notification module structure
The `notifications` domain package has two layers, so new channels never touch domain code:

```
notifications/
  router.py        # event → category, level, recipients (spec §19.2) → channel resolution
  policy.py        # the channel resolution chain (§16.3)
  models.py        # notifications, notification_deliveries, preferences, policies, contact_points
  templates/       # <category>/<channel>.<lang>.j2
  channels/        # one class per channel (the "what"): in_app, email, web_push, sms, mobile_push, webhook
  providers/       # one adapter per external service (the "how"), selected by .env
  gateway.py       # optional: hand all external deliveries to one external notification server
```

Pipeline:
1. A domain event arrives from the outbox.
2. `router` maps it to a **category** and **level**, and resolves recipients.
3. `policy` resolves the channel set per recipient.
4. One transaction inserts the in‑app `notifications` row and one `notification_deliveries` row per extra channel (status `PENDING`), plus one queue job per delivery.
5. The `notify` queue worker renders the template in the recipient's language, calendar and digit style, and calls the channel → provider adapter.
6. The provider result or delivery receipt (`/internal/notify/callbacks/{provider}`) updates the delivery status.

### 16.2 Levels and channels
- **Levels** (ordered): `INFO` < `WARNING` < `CRITICAL` [spec §19.1]. Stored as an ordered enum, so a new level (e.g. `LOW` for digest‑only) can be inserted without schema changes.
- **Channels:**

| Channel | MVP status | Provider adapters (examples) |
|---|---|---|
| `IN_APP` | M2 | built‑in (always on, cannot be disabled) |
| `EMAIL` | auth flows only (NOT‑002); operational email post‑MVP | reuses the email abstraction: SMTP, email API |
| `WEB_PUSH` | M4 (NOT‑003) | VAPID Web Push |
| `SMS` | post‑MVP; adapter slot ready | per‑country SMS gateways (country routing) |
| `MOBILE_PUSH` | post‑MVP | FCM / APNs (only if native apps are added) |
| `WEBHOOK` | post‑MVP | tenant‑configured HTTPS endpoint (signed); covers chat tools |

### 16.3 Channel resolution chain
For each (recipient, notification), a channel is used only if every step allows it:

1. **Platform:** the channel is enabled in `NOTIFY_CHANNELS`, and the level is ≥ `NOTIFY_MIN_LEVEL_<CHANNEL>`.
2. **Entitlement:** feature `notify.<channel>` is true and quota `notify.<channel>.monthly` is not exhausted (from the AMS, §6.8). Exhausted quota → delivery `SUPPRESSED`, in‑app still delivered.
3. **Tenant / org‑unit policy:** a level → channels matrix set by Managers. Default: INFO → IN_APP; WARNING → IN_APP + WEB_PUSH; CRITICAL → IN_APP + WEB_PUSH + SMS + EMAIL (each only if enabled).
4. **User preferences:** per category × channel opt‑in/mute [NOT‑004], quiet hours (non‑critical deliveries are deferred to the end of quiet hours), and a **verified contact point** (phone verified by OTP for SMS, email verified, push subscription active). CRITICAL cannot be muted for IN_APP and WEB_PUSH.

### 16.4 Delivery reliability
- **Idempotency:** unique `(event_id, user_id, channel)` on `notification_deliveries`.
- **Retries:** exponential backoff up to `NOTIFY_MAX_RETRIES`, then `FAILED` (visible in the admin console).
- **CRITICAL escalation:** if a CRITICAL notification is not read within `NOTIFY_CRITICAL_ACK_TIMEOUT_SECONDS`, the next channel in `NOTIFY_CRITICAL_FALLBACK` is tried.
- **Circuit breaker per provider**; SMS routes may list a backup provider.
- **Digest:** INFO deliveries on external channels can be batched per user every `NOTIFY_DIGEST_INTERVAL_MINUTES`.
- **Rate limits** per tenant and channel protect cost and providers.
- **Metering:** sent SMS/push counts go into the AMS `usage.report`.
- **Templates:** SMS templates have a length budget (Persian is UCS‑2: 70 characters per segment) and carry a short deep link.

### 16.5 External notification server
`NOTIFY_GATEWAY=external` sends every non‑in‑app delivery as one normalized, HMAC‑signed HTTP request to `NOTIFY_GATEWAY_URL`:
```json
{ "delivery_id": "…", "channel": "SMS", "level": "CRITICAL", "category": "safety.stop",
  "recipient": { "user_ref": "…", "phone": "+98…", "email": null, "push": [], "locale": "fa" },
  "rendered": { "title": "…", "body": "…", "link": "https://…" }, "callback_url": "…/internal/notify/callbacks/gateway" }
```
This lets a separate notification server (self‑built or an off‑the‑shelf product) take over delivery with no CMMS code change. `NOTIFY_GATEWAY=internal` uses the built‑in channel adapters.

### 16.6 Tables
```
notifications(...)                                         -- in-app record, partitioned (existing)
notification_deliveries(id, notification_id, event_id, user_id, channel, provider, status
    PENDING|SENT|DELIVERED|READ|FAILED|SUPPRESSED|DEFERRED, attempts, next_attempt_at,
    provider_message_id, error, created_at, updated_at)    -- partitioned
    UNIQUE (event_id, user_id, channel)
notification_policies(org_unit_id, level, channels text[], updated_by, updated_at)
notification_preferences(user_id, category, channel, enabled, quiet_hours jsonb)
contact_points(id, user_id, type EMAIL|PHONE|WEB_PUSH|MOBILE_PUSH, value, verified_at, active, meta jsonb)
tenant_webhooks(id, org_unit_id, url, secret_ref, categories text[], min_level, active)
```

### 16.7 Configuration
```
NOTIFY_CHANNELS=in_app,email,web_push        # platform-enabled channels
NOTIFY_GATEWAY=internal                      # internal | external
NOTIFY_GATEWAY_URL=
NOTIFY_GATEWAY_SECRET=
NOTIFY_MIN_LEVEL_EMAIL=WARNING
NOTIFY_MIN_LEVEL_WEB_PUSH=WARNING
NOTIFY_MIN_LEVEL_SMS=CRITICAL
NOTIFY_MIN_LEVEL_WEBHOOK=INFO
NOTIFY_WEB_PUSH_VAPID_PUBLIC_KEY=
NOTIFY_WEB_PUSH_VAPID_PRIVATE_KEY=
NOTIFY_WEB_PUSH_SUBJECT=mailto:ops@example.com
NOTIFY_SMS_ROUTES=IR:sms_ir_main,*:sms_intl  # country → provider id (first match wins)
NOTIFY_SMS_BACKUP_ROUTES=IR:sms_ir_backup
NOTIFY_PROVIDER__<ID>__TYPE=                 # adapter class for a provider id
NOTIFY_PROVIDER__<ID>__URL=
NOTIFY_PROVIDER__<ID>__API_KEY=
NOTIFY_PROVIDER__<ID>__SENDER=
NOTIFY_MOBILE_PUSH_PROVIDER=                 # fcm | apns | (empty)
NOTIFY_CRITICAL_FALLBACK=web_push,sms,email
NOTIFY_CRITICAL_ACK_TIMEOUT_SECONDS=300
NOTIFY_MAX_RETRIES=5
NOTIFY_DIGEST_INTERVAL_MINUTES=60
NOTIFY_QUIET_HOURS_DEFAULT=22:00-07:00
NOTIFY_RETENTION_DAYS=30
```
Adding a provider = one adapter class in `providers/` + its `NOTIFY_PROVIDER__<ID>__*` settings.

---

## 17. BACKGROUND PROCESSING

| Job | Queue | Schedule / trigger |
|---|---|---|
| Launch‑slot dispatcher, cycle evaluation | scheduler | every minute; on meter reading |
| Deadline watcher, SLA sweeper, snooze sweeper | scheduler | every 5 min |
| Outbox dispatcher | default | continuous |
| Invitation expiry | default | hourly |
| Notification deliveries (external channels), CRITICAL escalation, digests | notify | on event; escalation check every minute; digest per interval |
| Entitlement refresh / reconcile, AMS provisioning retry, usage report | default | every 5 min / nightly / on tenant creation / daily |
| Notification partition maintenance | default | daily |
| Soft‑delete purge eligibility (30‑day restore window end) | default | daily |
| Reorder evaluation | inventory | on posting; nightly |
| Ledger reconciliation | inventory | nightly |
| File scan, thumbnails, HEIC conversion | files | on upload |
| Manual ingestion (extract → OCR → chunk → embed) | ingestion | on document upload / reprocess |
| AI generation, troubleshooting, auto‑fill | ai | on request |
| Exports, PDFs, scheduled reports | reports | on request; scheduled‑report dispatcher every 5 min |
| Imports (validate, commit), zone clone | imports | on request |
| KPI materialized view refresh | reports | every 15 min |
| Training anonymization pipeline | training | weekly |
| Asset counter recount, cycle instance audit | default | nightly |

- **Job tracking:** user‑visible jobs write to `jobs` [NOT-007].
- **Retries:** exponential backoff (max 5) for transient errors. Failed jobs are visible in the admin console with their payload and error.
- **Idempotency:** every job carries a key, stored in Redis for 24 h.

---

## 18. SEARCH

- **Unified index table** `search_entries(tenant_id, org_unit_id, zone_path, entity_type, entity_id, code, title jsonb, body_norm text, tsv tsvector, updated_at)`, maintained by outbox handlers.
- **Indexes:** GIN on `tsv` (config `simple` over `norm_fa` text) and GIN `gin_trgm_ops` on `code` and `body_norm`.
- **Query:**
  1. Normalize the input.
  2. Exact code/number match first.
  3. Then a trigram + ts_rank blend.
  4. Permission and zone filters in the WHERE clause (RLS + scope).
  5. Top 5 per type.
- **Manual content search:** hybrid retrieval over `document_chunks`, combining `ts_rank` on `text_norm` and cosine similarity on `embedding` (HNSW index) with Reciprocal Rank Fusion. Filtered by tenant, org unit set, and document links accessible to the user.

---

## 19. AI SUBSYSTEM

### 19.1 Provider abstraction
```python
class LLMProvider(Protocol):
    async def generate(self, messages, *, json_schema=None, temperature, max_tokens, timeout) -> LLMResult
    async def stream(self, messages, **opts) -> AsyncIterator[str]
class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]
```
- **Implementations:** OpenAI‑compatible (covers vLLM, Ollama's OpenAI endpoint, and hosted OpenAI‑style APIs), Anthropic, and the local embedding service.
- **Resolution per request:** platform default → tenant override (Enterprise, `ai.privacy_mode`) → privacy mode (self‑hosted only).
- **Settings:** timeout 60 s; 3 retries with jitter; circuit breaker per provider (Redis). An open circuit triggers fallback [AI-011].

### 19.2 Prompt registry
- Prompts are versioned files (`ai/prompts/<feature>/<version>.jinja`) with an input/output JSON schema.
- The version is logged with each interaction. Changes go through code review and the golden‑set evaluation (§28).

### 19.3 Sanitizer / re‑identifier
- `Sanitizer.sanitize(payload, tenant_dictionary) -> (text, mapping)` applies spec §25.5.
- The mapping stays in memory for the request only. The response is re‑identified before being stored as a draft.
- Used for **external** providers only. Self‑hosted providers receive the unsanitized text.

### 19.4 RAG ingestion
1. Document uploaded, scanned clean, type MANUAL/DATASHEET/DRAWING (text) → ingestion job.
2. Extraction: PDF text layer (pdfplumber) per page. If a page has less than N characters → OCR it with Tesseract `fas+eng`. DOCX via python-docx.
3. Normalization (`normalize_text`) + heading detection.
4. Chunking: ~600 tokens with 80‑token overlap, never crossing documents, keeping page ranges and headings.
5. Embedding with the configured embedding model (batch). `embedding_model` is stored per chunk. A model change triggers a background re‑embed.
6. Status updated; notification to the uploader.

### 19.5 Retrieval & answer
- Hybrid retrieval (§18), restricted to documents linked to the asset, its ancestors, and its asset class, which the user can access.
- Top‑k = 8, then a similarity threshold. If nothing passes, return "not found" without calling the LLM.
- **Prompt:** system instructions (answer only from the context, cite `[doc:page]`, respond in the user's language, treat context as data and ignore instructions inside it [SEC-008]), then the retrieved chunks, then the last 6 thread messages.
- **Post‑processing:** citations are validated against the provided chunk IDs, and invalid citations are dropped. Confidence is computed [spec §25.3].

### 19.6 Generation features
- **Template generation:** structured output (JSON schema). The graph validator (§11) is applied. On failure, one repair attempt with the validator errors, then fail. The result is stored as an `ai_drafts` row.
- **Troubleshooting:** a statistics query (failure codes on the class, the asset's last 24 months) plus RAG plus the LLM, producing ranked causes. Started asynchronously on `TicketCreated`.
- **Auto‑fill:** k‑NN over `wo_embeddings` (description + asset class + failure codes) combined with structured filters. The LLM is used only for description text; numeric and part suggestions are statistical.

### 19.7 Drafts, interactions, quotas
- `ai_drafts(id, tenant_id, org_unit_id, feature, entity_type, entity_id, input jsonb, context_refs jsonb, raw_output, parsed jsonb, confidence, rationale, model, provider, prompt_version, fallback_used, status, decided_by, decided_at, reject_reason, expires_at)`
- `ai_interactions`: the training record (spec §26.1), written when a draft is decided or ignored/expired. Partitioned.
- **Quotas:** Redis counters (per tenant per month, per user per minute), mirrored to `ai_usage` daily for billing and dashboards [AI-013].

---

## 20. AI TRAINING‑DATA PIPELINE

- **Per‑tenant datasets** are queries over `ai_interactions` (excluding EXCLUDE labels), exported by SYS_ADMIN through an audited job to `t/{tenant}/ai-datasets/…`, only if the tenant's contract flag allows it [AIT-006].
- **Broad dataset** [spec §26.3]:
  - Runs in the `training` worker with a **separate DB role** (`training_reader`: read‑only on eligible `ai_interactions` columns; `training_writer`: write only to schema `training_broad`).
  - Outputs to the separate bucket `aiamms-training-broad`.
  - Pipeline stages are pure functions over batches:
    1. dictionary redaction (tenant dictionary built from master data at batch time, then discarded)
    2. regex redaction
    3. NER
    4. generalization
    5. stripping/shuffling
    6. PII quality gate
  - Records in `training_broad` have no tenant/source columns and no hashes of source IDs. A processed‑flag in `ai_interactions` (tenant side) prevents re‑processing [AIT-007].
- **Tenant‑specific adapters:** out of MVP runtime scope. Datasets are produced; serving tenant adapters requires `model_scope = tenant_id` in the provider resolution (hook present, used when adapters exist).

---

## 21. MCP SERVER

### 21.1 Position
```
[External AI agent] ──MCP (stdio | Streamable HTTP)──▶ [MCP server] ──▶ aiamms.domain (commands/queries) ──▶ PostgreSQL / Redis / MinIO / Celery
```
- Separate container `mcp`, exposed under `/mcp` through Nginx. Allowed origins are restricted. It is disabled with `MCP_ENABLED=false`.
- The server advertises the supported MCP spec versions and rejects unsupported clients.

### 21.2 Authentication & context
- A bearer JWT (user) or an API key (`aiamms_mk_<id>_<secret>`) is looked up by ID and compared by hash.
- The context is built exactly as in §6.2, with `actor_type = MCP_AGENT`, key ID, role, zone scope, and the read‑only flag.
- SYS_ADMIN tokens are rejected [MCP-004].

### 21.3 Tools = commands
- Each MCP tool is generated from a domain command's Pydantic schema, plus a description and a gate flag.
- Resources are generated from query objects. Pagination uses cursors.
- **Dry‑run:** the command executes in a transaction with `SAVEPOINT`. Effects (diff, events) are collected, then everything is rolled back. The outbox rows roll back too.
- **Confirmation gate:** the gated command is serialized into `mcp_pending_actions(id, key_id, command jsonb, preview jsonb, required_permission, status, expires_at, decided_by)`. It returns `PENDING_CONFIRMATION`. UI approval re‑validates and executes the command, with the approver as confirming actor.
- **Operations log:** `mcp_operations(id, key_id, command, result, entity_refs, compensation jsonb, executed_at, undone_at)`. Undo checks, via `updated_at`/`version`, that no later human change touched the entity refs, then runs the compensations in reverse [MCP-009].
- **Limits:** Redis rate limits per key and tool class; hourly ceilings for WO/ticket creation [MCP-007].
- **Audit:** every call is logged with the input SHA‑256, result, and key ID [MCP-010].

### 21.4 Configuration
```
MCP_ENABLED=true
MCP_TRANSPORT=http|stdio
MCP_HTTP_PORT=8100
MCP_ALLOWED_ORIGINS=...
MCP_CONFIRMATION_REQUIRED=true
MCP_PENDING_TTL_HOURS=24
MCP_UNDO_WINDOW_MINUTES=5
```

---

## 22. API ARCHITECTURE

### 22.1 Conventions
- Base path `/api/v1`, JSON, OpenAPI 3.1 generated by FastAPI.
- Active org unit via header `X-Org-Unit`. Language via `Accept-Language` (fallback: user setting).
- **Pagination:** cursor‑based for large lists (`cursor`, `limit`), offset (`page`, `page_size`, `total`) for small admin lists.
- Filtering and sorting via explicit whitelisted query parameters per endpoint.
- Optimistic concurrency: `If-Match: <version>` on PATCH/state commands. A mismatch returns `409`.
- Idempotency: the `Idempotency-Key` header is supported on all POST commands (stored 24 h).
- State changes are exposed as **command endpoints** (`POST /work-orders/{id}/complete`), not as status PATCHes.
- Errors: spec §30 format.

### 22.2 Endpoint catalogue (summary)
```
Auth         POST /auth/signup | /auth/verify-email | /auth/login | /auth/refresh | /auth/logout
             POST /auth/forgot-password | /auth/reset-password ; GET/PATCH /me ; GET/DELETE /me/sessions
Tenancy      GET/PATCH /org-units/{id} ; POST /org-units (sub-org) ; POST /org-units/{id}/archive|restore
             GET/POST /memberships ; PATCH/DELETE /memberships/{id}
             GET/POST /invitations ; POST /invitations/{token}/accept ; DELETE /invitations/{id}
             GET /subscription (cached entitlement + AMS billing summary) ; POST /subscription/checkout
             (returns AMS-hosted checkout URL) ; POST /ownership/transfer
             GET/PUT /work-calendar ; POST /tenant/export ; POST /tenant/close
Locations    CRUD /zones ; POST /zones/{id}/clone ; POST /zones/{id}/restore
Systems      CRUD /systems ; PUT /systems/{id}/zones
Assets       CRUD /asset-classes ; CRUD /assets ; POST /assets/{id}/move|install|remove|decommission|
             recommission|restore ; GET /assets/{id}/timeline|components|cost ; GET/PUT /assets/{id}/bom
             GET /qr/{token} ; POST /labels (batch PDF)
Meters       CRUD /assets/{id}/meters ; POST /meters/{id}/readings ; POST /readings/bulk
             POST /readings/{id}/void ; POST /meters/{id}/replace ; POST /cycle-instances/{id}/reset-baseline
Cycles       CRUD /cycles ; POST /cycles/{id}/suspend|activate|launch ; GET /cycles/due-for-launch
             GET/PATCH /cycle-instances/{id} ; GET /cycles/{id}/evaluations ; GET /pm-forecast
Templates    CRUD /templates ; POST /templates/{id}/versions ; PUT /template-versions/{id}/graph
             POST /template-versions/{id}/validate|publish|retire ; GET /templates/search
Work orders  GET/POST /work-orders ; GET /work-orders/{id}
             POST /work-orders/{id}/acknowledge|start|hold|resume|snooze|reject|reassign|cancel|
             complete|qc-approve|qc-return|reopen|save-as-template
             PATCH /work-orders/{id}/nodes/{nodeId} ; POST /work-orders/{id}/nodes/{nodeId}/permit|sign
             POST /work-orders/{id}/labour|external-costs|follow-up ; GET /backlog ; GET /schedule
Labour       CRUD /crafts ; CRUD /teams ; CRUD /certifications ; GET/POST/PATCH /labour-entries
Tickets      GET/POST /tickets ; GET /tickets/{id}
             POST /tickets/{id}/claim|assign|cancel|convert|report|accept|feedback|escalation-decision
Reliability  CRUD /failure-codes ; GET/POST/PATCH /downtime-events ; POST /assets/{id}/operating-state
             POST /state-causes/{id}/override
Inventory    CRUD /parts ; CRUD /uoms ; CRUD /storerooms ; CRUD /storerooms/{id}/bins
             GET /stock (balances, availability) ; GET /stock/ledger
             POST /stock/issue|return|transfer|adjust ; GET/POST /reservations ; POST /reservations/{id}/release
             GET/PUT /reorder-policies ; GET /reorder-suggestions ; POST /reorder-suggestions/convert
             CRUD /count-sheets ; POST /count-sheets/{id}/start|submit|approve|recount
             GET /serials ; GET /lots
Purchasing   CRUD /vendors ; CRUD /vendors/{id}/parts
             CRUD /requisitions ; POST /requisitions/{id}/submit|approve|reject|cancel
             CRUD /purchase-orders ; POST /purchase-orders/{id}/submit|approve|reject|send|close|cancel
             GET /purchase-orders/{id}/pdf ; POST /receipts ; POST /receipts/{id}/reverse
             POST /vendor-returns
Notifications GET /notifications ; POST /notifications/{id}/read ; POST /notifications/read-all
             GET /notifications/stream (SSE) ; POST /push-subscriptions ; CRUD /announcements
             GET/PUT /me/notification-preferences ; POST /me/contact-points (+ /verify)
             GET/PUT /org-units/{id}/notification-policy
Internal     POST /internal/ams/v1/msg (AMS callbacks) ; POST /internal/notify/callbacks/{provider}
             (delivery receipts) — not under /api, restricted at Nginx
             POST /announcements/{id}/ack
Reporting    GET /dashboards/me ; GET /kpis ; GET /kpis/consolidated ; GET /reports/{type}
             POST /exports ; CRUD /scheduled-reports ; GET /audit-logs ; POST /audit-logs/export
Search       GET /search?q= ; GET /search/manuals?q=
Collab       GET/POST /comments?entity= ; PATCH/DELETE /comments/{id} ; CRUD /saved-views
Files        POST /files (multipart or pre-signed upload init/complete) ; GET /files/{id}/url
             CRUD /documents ; POST/DELETE /documents/{id}/links ; POST /documents/{id}/reprocess
Import       GET /imports/templates/{entity} ; POST /imports ; GET /imports/{id} ; POST /imports/{id}/commit
Onboarding   GET /starter-templates ; POST /onboarding/apply ; POST /onboarding/remove-samples
AI           POST /ai/templates/generate ; POST /ai/troubleshoot ; POST /ai/autofill
             GET/POST /ai/drafts/{id} (approve|reject|suggest) ; CRUD /ai/threads ; POST /ai/threads/{id}/messages
             GET /ai/usage ; GET/PATCH /ai/training-log ; GET/PATCH /ai/settings
MCP admin    CRUD /mcp/keys ; POST /mcp/keys/{id}/rotate|revoke ; GET /mcp/pending-actions
             POST /mcp/pending-actions/{id}/approve|reject ; GET /mcp/activity
Jobs         GET /jobs ; GET /jobs/{id}
Offline      POST /sync/commands (batch of queued commands with idempotency keys)
Admin        /admin/tenants ; /admin/support-sessions ; /admin/jobs ; /admin/ai ; /admin/datasets
Health       GET /health/live ; GET /health/ready
```

---

## 23. FILE STORAGE

- **Storage port:** `put`, `get`, `delete`, `presign_get`, `presign_put`, `head`, `copy`. Adapters: local FS, S3/MinIO.
- **Upload flow:**
  1. The client requests pre‑signed PUT.
  2. It uploads to the quarantine prefix.
  3. It calls complete.
  4. The `files` worker validates magic bytes and size, then scans with ClamAV.
  5. It creates a thumbnail/preview (Pillow; HEIC via pillow-heif), strips EXIF GPS, and moves the file to its final key.
  6. `scan_status = CLEAN`.
  7. If the file is a document, ingestion is enqueued.
- Download URLs are pre‑signed for 10 min and generated only after a policy check.
- Tier storage quota is tracked by a counter on the tenant, updated on complete/delete.

---

## 24. REPORTING & EXPORTS

- **Operational lists:** indexed queries on the transactional tables.
- **KPI read models:** materialized views per org unit and day (e.g. `mv_wo_daily`, `mv_downtime_daily`, `mv_cost_daily`, `mv_stock_value_daily`), refreshed concurrently every 15 min. KPIs for arbitrary periods aggregate the daily rows. Formulas follow spec §20.
- **Exports:** background job → CSV (UTF‑8 BOM) / XLSX (openpyxl, RTL sheet direction for fa) → object storage (7‑day expiry) → notification with a link.
- **PDF:** HTML templates rendered by WeasyPrint (summary reports, PO, receipts, labels, WO print).
- **Scheduled reports:** `scheduled_reports(id, definition jsonb, rule jsonb, recipients uuid[], language, next_run_at)`. The dispatcher uses the recurrence engine (§10.1).

---

## 25. FRONTEND ARCHITECTURE

- **App shell:**
  - Header with org‑unit switcher, global search, notification bell, task centre, and language/calendar indicator.
  - Side navigation that becomes a bottom bar on mobile.
- **Route modules:**
  - Dashboard
  - Assets (zones, systems, assets, classes)
  - Maintenance (cycles, PM forecast, templates)
  - Work (work orders, backlog, schedule)
  - Tickets
  - Inventory (parts, stock, storerooms, counts, reorder)
  - Purchasing (requisitions, POs, receipts, vendors)
  - Reports
  - Audit
  - AI (drafts, activity)
  - Settings (org, users, calendar, failure codes, crafts, MCP keys, AI)
  - Admin (SYS_ADMIN)
- **Permission‑aware UI:** the server returns the permission set for the active org unit (`GET /me`). Components use `can(permission)`. The server still enforces every rule.
- **Date and number components:**
  - `<DateView>`, `<DateInput>`, and `<RecurrenceBuilder>` render in the user's calendar.
  - `<Num>` renders numbers in the user's digit style.
  - `<Code>` renders an LTR‑isolated Latin code.
- **Workflow editor:** list mode (sequential) and graph mode (React Flow) with a condition builder that produces the spec grammar. Server‑side validation results are shown inline.
- **Offline (MOB‑005):**
  - The service worker precaches the app shell. Runtime caching covers assigned WOs and asset cards (stale‑while‑revalidate), plus opened manuals (cache‑first, LRU, 200 MB cap).
  - An IndexedDB command queue holds `{idempotency_key, command, payload, created_at}`. It is flushed via `POST /sync/commands` when online. Per‑command results are shown in "Sync issues".
- **Testing hooks:** `data-testid` on all actions; Storybook stories rendered in both fa (RTL) and en (LTR).

---

## 26. DEPLOYMENT

### 26.1 Topology
```
[Internet] → [WAF/CDN (optional)] → [Nginx]
                                      ├── /            → SPA static (PWA)
                                      ├── /api/*       → api (FastAPI, Uvicorn/Gunicorn)
                                      ├── /mcp/*       → mcp (restricted)
                                      └── /q/*         → SPA route (QR landing)
Internal: api, mcp, worker-{scheduler,default,notify,inventory,files,ingestion,ai,reports,imports,training},
          beat, postgres, redis, minio, clamav, embeddings, [ollama|vllm optional]
Commercial (isolated): ams + ams-db — same stack or a different host/region; reached only via AMS_URL
```

### 26.2 Docker Compose (development & self‑hosted)
Services:
- `nginx`
- `web` (build‑only; static files served by nginx)
- `api`
- `mcp`
- `worker` (all queues, concurrency configurable)
- `beat` (exactly one)
- `db` (postgres 16 + pgvector, persistent volume)
- `redis` (AOF persistence)
- `minio`
- `clamav`
- `embeddings`
- `ams` + `ams-db` (SaaS profile only; self‑hosted uses `AMS_MODE=static`)
- optional profiles: `ollama`, `monitoring` (Prometheus/Grafana/Loki), `flower`

A single‑server self‑host is ≤ 30 min with the installation guide [NFR-016]. Minimum spec without a local LLM: 8 vCPU, 16 GB RAM, 200 GB SSD (recommended 32 GB RAM, 500 GB NVMe) — ClamAV and the embedding model alone need ~5–7 GB. A local LLM needs its own sizing (GPU recommended).

### 26.3 Kubernetes (SaaS)
- Helm chart with deployments per component.
- HPA on api/mcp (CPU, latency) and on workers (queue length via KEDA).
- Beat is a single replica with leader lock.
- Managed PostgreSQL recommended (with pgvector); PgBouncer in transaction mode (RLS settings use `SET LOCAL` inside transactions, which is compatible).
- S3‑compatible storage.

### 26.4 Environments & releases
- dev / staging / prod with separate secrets.
- Migrations follow expand‑and‑contract so rolling deploys work [OPS-004].
- Feature flags: `AMS_MODE` (remote | static; replaces `TIER_ENFORCEMENT`/`BILLING_PROVIDER`), `NOTIFY_CHANNELS`, `NOTIFY_GATEWAY`, `AI_ENABLED`, `AI_PROVIDER`, `MCP_ENABLED`, `CLAMAV_ENABLED`.

### 26.5 Backup & recovery
- **PostgreSQL:** pgBackRest (or managed PITR) with continuous WAL archiving (RPO ≤ 15 min), daily full backups kept 30 days, and a quarterly restore drill [NFR-007].
- **Object storage:** versioning + replication or nightly sync to secondary storage.
- The restore runbook lives in `docs/server installation and initiation instructions.md`.

---

## 27. OBSERVABILITY & OPERATIONS

- **Logs:** structured JSON on stdout: `request_id`, `tenant_id`, `org_unit_id`, `actor`, `route`, `latency`, `status`. Prompts and PII are redacted.
- **Metrics (Prometheus):**
  - API latency/error rates per route
  - queue depth and age per queue
  - cycle evaluation duration and outcomes
  - WOs generated
  - SLA breaches
  - ledger reconciliation mismatches
  - AI latency, tokens, fallback rate, and acceptance rate
  - RAG no‑answer rate
  - MCP calls and pending actions
  - file scan failures
- **Tracing:** OpenTelemetry (API → DB → worker). Optional exporter.
- **Error tracking:** Sentry‑compatible, with PII scrubbing.
- **Health:** `/health/live` (process) and `/health/ready` (DB, Redis, storage, embedding service; AI provider, AMS, and notification providers reported as degraded, not failed) [OPS-005].
- **Alerts:** scheduler lag > 10 min, queue age > 15 min, reconciliation mismatch, backup failure, error rate > 2%.

---

## 28. TESTING STRATEGY

| Layer | Focus |
|---|---|
| Unit | Domain commands, state machines (table‑driven from spec), recurrence engine (shared Jalali/Gregorian vectors), normalization vectors, workflow graph validator and runtime, cost and KPI formulas, confidence formulas |
| Property‑based (Hypothesis) | Ledger invariant (Σ ledger = balances), moving average, meter monotonicity with rollover/replacement, workflow advance never deadlocks on a valid graph |
| Concurrency | Parallel issues of last unit, parallel cycle evaluation workers (no duplicates), number sequences |
| Integration (API) | RBAC matrix (generated from `permissions.py` vs spec §4 table), tenant/sub‑org isolation suite (every endpoint probed with a foreign ID → 404), zone‑scope suite |
| MCP | Tool parity with REST, gates, dry‑run leaves no trace, undo conflicts, SYS_ADMIN rejection |
| AI | Mock providers; schema/repair handling; RAG isolation (cross‑tenant and cross‑sub‑org); no‑context behaviour; prompt‑injection fixtures; sanitizer and anonymizer PII fixtures (fa + en); **golden sets** per feature evaluated on prompt/model change |
| Frontend | Component tests; RTL/LTR visual snapshots; Jalali date input; offline queue & sync conflicts |
| E2E (Playwright) | Per milestone: signup→org→sub‑org; asset tree with components & move; cycle → WO → complete (FIXED/FLOATING); ticket loop & escalation & conversion; issue parts & reorder → PR → PO → receipt; QR scan flow; AI draft approval; fa/Jalali full run |
| Performance | k6 scenarios for NFR‑001/003; scheduler benchmark for NFR‑004 |
| Security | OWASP ZAP baseline in CI, dependency & container scanning, secret scanning |

**CI:**
1. Lint (ruff, eslint incl. RTL rule), type check (mypy, tsc).
2. Tests.
3. Alembic migration up/down check.
4. Build images.
5. Scan.
6. Deploy staging.
7. Manual approval.
8. Deploy prod.

---

## 29. NFR REALIZATION

| NFR | Mechanism |
|---|---|
| NFR‑001 latency | Indexed queries, cursor pagination, membership cache, read models for KPIs, async for heavy work |
| NFR‑002 frontend | Code splitting per route module, lazy React Flow/ECharts, self‑hosted subset fonts |
| NFR‑003 scale | Partitioned append tables, `org_unit_id` leading indexes, horizontal API/workers, PgBouncer |
| NFR‑004 scheduler | Precomputed `next_due_at`, batch evaluation, advisory locks, horizontal scheduler workers |
| NFR‑006 availability | Stateless replicas, health‑based rollout, managed DB HA |
| NFR‑007 RPO/RTO | WAL archiving PITR, object versioning, restore drills |
| NFR‑010 accessibility | Semantic components, axe checks in CI for both directions |
| NFR‑011 ASVS L2 | §7, §23, §30 controls; ZAP; review checklist |
| NFR‑014 traceability | Tests tagged with requirement IDs; CI report of M‑priority IDs without tests |

---

## 30. SECURITY ARCHITECTURE (SUMMARY)

- **Transport:** TLS 1.2+ at Nginx/WAF, HSTS, secure cookies.
- **Identity:** Argon2id; rotating refresh tokens with reuse detection; lockout; audited support sessions.
- **Authorization:** a single policy layer for REST/MCP; RLS as defence in depth; zone‑scope repository tests.
- **Input:** Pydantic validation; ORM parameterization; condition language parsed to an AST (no eval); XLSX import with formula evaluation disabled and cell formulas stripped.
- **Output:** React escaping; strict CSP (no inline scripts); `X-Content-Type-Options`; downloads served with `Content-Disposition: attachment` for non‑image types.
- **Files:** allow‑list plus magic bytes, ClamAV quarantine, private buckets, short pre‑signed URLs.
- **AI:** sanitizer for external providers, retrieval scoped by tenant/org unit/document links, prompt‑injection hardening, no write tools from the in‑app assistant, separate credentials and storage for training data.
- **MCP:** hashed scoped keys, gates, rate limits, full audit.
- **Audit integrity:** append‑only table (trigger blocks UPDATE/DELETE, `app_user` has INSERT only) plus a hash chain.
- **Secrets:** environment or secret manager; per‑environment keys; JWT key rotation with `kid`.

---

## 31. ARCHITECTURAL DECISIONS (ADR SUMMARY)

| # | Decision | Rationale |
|---|---|---|
| ADR‑01 | Modular monolith (FastAPI) + Celery, shared domain package for API, MCP, workers | One behaviour, three entry points; simple for self‑hosting |
| ADR‑02 | PostgreSQL for OLTP, vectors (pgvector), search (FTS + trigram), and hierarchies (ltree) | Fewer moving parts; tenant isolation in one place |
| ADR‑03 | `tenant_id` + `org_unit_id` with RLS | Sub‑orgs need isolation below tenant level |
| ADR‑04 | Location (zone) separated from asset; assets nest physically via `parent_asset_id` | Decision: location is an address, the asset is maintained; supports components (agitator in tank) |
| ADR‑05 | Commands + transactional outbox | Uniform audit, idempotency, dry‑run, undo, reliable side effects |
| ADR‑06 | Snapshot WOs (copied nodes/edges) | Template changes never alter execution records |
| ADR‑07 | Own recurrence engine (no raw cron) with Jalali support | Cron cannot express Jalali months; users need a builder |
| ADR‑08 | Cumulative meters + per‑cycle baselines | Preserves lifetime data for reliability KPIs |
| ADR‑09 | Append‑only stock ledger + locked balance projection, moving average cost | Auditability and correctness under concurrency |
| ADR‑10 | Safety state from explicit cause records | Deterministic, explainable propagation and clearing |
| ADR‑11 | Self‑hosted multilingual embeddings by default | Persian quality; manuals are not sent to third parties for indexing |
| ADR‑12 | AI outputs are drafts requiring approval | Safety and accountability |
| ADR‑13 | Broad training data in separate schema/bucket with no back‑references | Non‑addressability by construction |
| ADR‑14 | MCP tools generated from domain commands | Parity with REST; no second rule set |
| ADR‑15 | PWA with limited offline command queue | Field connectivity without full offline complexity |
| ADR‑16 | Commercial logic in a separate Account Management Service; CMMS consumes signed + encrypted entitlements and enforces keys, never plan names | Country‑specific payments and policies change without CMMS releases; AMS can move or serve several CMMS deployments; CMMS keeps running when AMS is down |
| ADR‑17 | Notifications split into router/policy (domain) and channel/provider adapters selected by `.env`, with an optional external gateway | New channels (SMS, mobile push, webhooks) and per‑country providers are added without touching domain code |

---

## 32. TECHNICAL RISKS

| Risk | Mitigation |
|---|---|
| Workflow engine (parallel + conditional) complexity | Sequential engine in M2; graph engine in M4 behind the same runtime interface; property tests |
| Persian OCR quality on scanned manuals | Tesseract `fas` baseline; flag low‑confidence pages; allow a re‑upload of a text version |
| Persian PDF rendering and RTL edge cases | WeasyPrint + Vazirmatn; visual regression tests on PDFs |
| Anonymization misses (PII leakage into broad dataset) | Multi‑layer redaction, quality gate, human sampling, consent default per D3 |
| RLS performance with array membership | `org_unit_id` leading composite indexes; small arrays; benchmark in M1 |
| LLM cost overrun | Tier quotas, caching of retrieval, fallback mode, per‑feature token caps |
| Scope size of MVP | Milestone gating (M1–M5); each milestone releasable to pilot users |
