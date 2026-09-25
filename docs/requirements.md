# PROJECT AIAMMS
## AI‑Assisted Maintenance Management System
### Open‑Source CMMS Web SaaS — Requirements (MVP)

| Item | Value |
|---|---|
| Document version | 2.0 |
| Date | 2026‑09‑25 |
| Status | Draft for review |
| Authority | **This document is the source of truth for scope.** `project_specification.md` (behaviour) and `architecture.md` (implementation) must conform to it. Where they disagree, this document wins and the others must be corrected. |

---

## 0. DOCUMENT CONVENTIONS

### 0.1 Document Set
| Document | Answers | Contains |
|---|---|---|
| `requirements.md` | **What** and **why** | Numbered requirements, priority, milestone, acceptance criteria, scope boundaries, open decisions |
| `project_specification.md` | **Exactly how it behaves** | Business rules, field definitions, state machines, permission matrix, formulas, validation rules. References requirement IDs. |
| `architecture.md` | **How it is built** | Components, data model, technology decisions, NFR realization. References requirement and spec sections. |

### 0.2 Requirement IDs
Each requirement has a stable ID `<AREA>-<NNN>` (e.g. `INV-012`). IDs are never reused. Deleted requirements are marked *Withdrawn*.

### 0.3 Priority (MoSCoW)
- **M** – Must: MVP cannot ship without it.
- **S** – Should: planned for MVP; may slip to first post‑MVP release only with explicit approval.
- **C** – Could: in MVP only if time permits.

### 0.4 Delivery Milestones (all within MVP)
The full MVP scope below is retained. Milestones define **build order**, not scope cuts.

| Milestone | Theme | Main content |
|---|---|---|
| **M1** | Foundation | Auth, tenancy & sub‑organizations, RBAC, Persian/English + Jalali, files, audit, zones, systems, assets, QR |
| **M2** | Preventive maintenance | Meters, cycle engine, checklists, sequential workflows, work orders, safety flags, notifications, labour |
| **M3** | Corrective & materials | Repair tickets, ticket→WO conversion, failure codes, downtime, inventory, purchasing (PO → receipt) |
| **M4** | Advanced & reporting | Parallel/conditional workflows & versioning, seasonal cycles, PM nesting, dashboards/KPIs, scheduled reports, bulk import, global search, onboarding templates, audit UI, PWA |
| **M5** | AI & MCP | AI generation, RAG assistant, troubleshooting copilot, auto‑fill, confidence, training data pipeline, MCP server |

> The AI track (M5) may be developed in parallel from M2 onward; it is scheduled last only for release gating.

### 0.5 Changes from v1
| Change | Reason |
|---|---|
| "Service Point / Node" renamed **Asset**; assets may contain component assets (e.g. agitator inside a tank) | Asset is what is maintained; physical containment must be modelled |
| Zones are **locations** (addresses); asset position = zone + free‑text position | "Location is just an address" decision |
| Single "6 levels" depth rule replaced by per‑dimension limits (org, zone, system, asset nesting) | Old rule was arithmetically inconsistent across documents |
| Inventory expanded: storerooms, bins, stock ledger, reservations, costing, cycle counts, serial/lot | Real CMMS inventory |
| Purchasing (vendors, requisition, PO, approval, receipt) added to MVP | Decision |
| Tickets may optionally be converted to corrective work orders | Decision |
| Meters are cumulative; "counter reset" now resets the **since‑last‑service** baseline, never the lifetime reading | Preserves reliability history (MTBF) |
| Added: work types, labour, failure codes, downtime, ticket SLA, PM fixed/floating scheduling, lead time, work calendars, PM nesting | Standard CMMS capabilities required for KPIs |
| STOREKEEPER role, ownership flag, zone‑scoped permissions added | Inventory & multi‑site operation |
| Full Persian (fa) and English (en) localization, Jalali calendar | Decision |
| AI training data: per‑tenant by default; broad training only on anonymized, sanitized, non‑addressable data | Decision |
| Backend framework fixed as **FastAPI** | Removes "FastAPI or Django" ambiguity |
| Non‑functional requirements quantified | Previously missing |

---

## 1. PROJECT PURPOSE & PHILOSOPHY

**AIAMMS** is an open‑source Computerized Maintenance Management System (CMMS) delivered as a web‑based multi‑tenant SaaS and as a self‑hostable distribution. It enables organizations to manage:

- Users, organizations and sub‑organizations with strict data isolation.
- Locations (zones) and hierarchical, physically nested assets.
- Preventive maintenance and inspection cycles driven by calendar, season, and meter readings.
- Checklists and workflows (sequential, parallel, and conditional), work orders, labour and costs.
- Repair tickets with an issuer‑review loop, optionally converted to corrective work orders.
- Spare parts inventory and purchasing (vendors, purchase orders, receipts).
- Reliability data: failure codes and downtime.
- Dashboards, scheduled reports, and full audit trails.
- An **AI copilot** that drafts, suggests, and auto‑fills, while humans review and approve.
- An **MCP server** exposing system functions to external AI agents under the same security rules.

**Core philosophy:** AI is the **copilot**. It speeds up work, reduces errors, and learns from human decisions, but **never overrides** human authority and never activates safety‑relevant content without human approval.

---

## 2. GLOSSARY

| Term | Definition |
|---|---|
| **Platform** | The whole AIAMMS SaaS installation, operated by the platform owner. |
| **Tenant** | A root organization and all its sub‑organizations. The unit of billing and of hard data isolation. |
| **Organization (Org)** | A root organization (tenant root). |
| **Sub‑organization (Sub‑org)** | A child organization unit inside a tenant (e.g. a plant or a subsidiary). Sibling sub‑orgs are isolated from each other. |
| **Org unit** | Either the root organization or a sub‑org. |
| **Zone** | A **location**: a site, building, floor, or area with an address and contact. Zones are places, not maintained items. |
| **System / Sub‑system** | A functional grouping of assets (e.g. "HVAC", "Chilled water loop"). May span multiple zones. |
| **Asset** | A physical item that is maintained, inspected, or repaired. It is the atomic maintenance unit. Previously called *Service Point* or *Node*. |
| **Component asset** | An asset that is physically on, at, or in a parent asset (e.g. an agitator inside a tank). |
| **Meter** | A cumulative measurement on an asset: operating hours, operation count, distance, or a generic numeric value. |
| **Reading** | A recorded meter value at a point in time. |
| **Cycle** | A preventive maintenance / inspection plan: what to do (checklist or workflow), on what (scope), and when (triggers). |
| **Trigger** | A condition that makes a cycle due: calendar, seasonal, or meter‑based. |
| **Work Order (WO)** | A dated execution instance of a checklist or workflow on a target, with assignments, labour, parts, and results. |
| **Work Item** | One step of a work order (a checklist line or a workflow task). |
| **Checklist** | A flat inspection template (Inspected / Pass / Fail per item). |
| **Workflow** | A task template that may contain sequential, parallel, and conditional steps. Versioned. |
| **Repair Ticket** | A request raised by an operator or manager reporting a problem. It may be resolved directly, or converted to a corrective work order. |
| **Part** | A stock‑keeping item (spare part or consumable). |
| **Storeroom / Bin** | A stock location (warehouse or storeroom) and a shelf position inside it. |
| **Stock ledger** | The append‑only record of every stock movement. On‑hand quantities are derived from it. |
| **Reservation** | Stock set aside for a planned work order. |
| **Purchase Requisition (PR)** | An internal request to buy parts or services. |
| **Purchase Order (PO)** | An approved order sent to a vendor. |
| **Receipt** | Registration of goods received against a PO. |
| **Failure code** | A structured problem → cause → action classification recorded on corrective work. |
| **Downtime event** | A recorded period during which an asset was not operating. |
| **Safety flag** | Hot Inspect / Pause for Inspection / Stop Until Complete: the operational impact of a task. |
| **Operating state** | The runtime state of an asset: Running, Restricted, Stopped, In Maintenance. Distinct from lifecycle status. |

---

## 3. PRODUCT & COMMERCIAL MODEL

| ID | Requirement | Pri | MS |
|---|---|---|---|
| COM-001 | The source code shall be released under an OSI‑approved licence. Proposed: **AGPL‑3.0** (see Open Decisions §33). | M | M1 |
| COM-002 | Two editions from one codebase: **SaaS** (multi‑tenant, tiers and billing enforced) and **Self‑hosted** (tier enforcement and billing disabled by configuration). | M | M1 |
| COM-003 | Subscription tiers apply at tenant level: | M | M1 |

| Tier | Max active assets (whole tenant) | Sub‑orgs | AI monthly quota | MCP |
|---|---|---|---|---|
| Free | 100 | 0 | Low | Read‑only |
| Pro | 1,000 | up to 5 | Medium | Read + write |
| Ultimate | Unlimited | Unlimited | High / configurable | Read + write |

| ID | Requirement | Pri | MS |
|---|---|---|---|
| COM-004 | The asset limit counts all assets (including component assets) whose lifecycle status is not DECOMMISSIONED. Zones, systems, and parts do not count. | M | M1 |
| COM-005 | The root org may allocate asset quotas to sub‑orgs. Unallocated capacity is shared by the whole tenant. | S | M1 |
| COM-006 | When a tenant exceeds its limit (e.g. after a downgrade), existing assets remain fully usable, but new assets cannot be created until under the limit. No data is deleted. | M | M1 |
| COM-007 | Billing is implemented behind a payment‑provider abstraction. The concrete provider(s) are an open decision. | M | M1 |
| COM-008 | Payment state per tenant: CURRENT, OVERDUE, SUSPENDED. OVERDUE: all features remain active **except creating new repair tickets**. SUSPENDED: read‑only access and data export only. | M | M1 |
| COM-009 | A new tenant may start with a time‑limited trial of the Pro tier (duration configurable, default 30 days). | C | M1 |

---

## 4. USER ACCOUNTS & AUTHENTICATION (AUTH)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| AUTH-001 | Self‑service signup with email + password. | M | M1 |
| AUTH-002 | Password policy: minimum 8 characters, at least 1 uppercase letter and 1 digit, not in a common‑password list. | M | M1 |
| AUTH-003 | Mandatory email verification with a single‑use, time‑limited token (24 h). | M | M1 |
| AUTH-004 | Login returns a short‑lived access token (15 min) and a rotating HttpOnly refresh token (7 days, sliding). | M | M1 |
| AUTH-005 | "Remember me" persistent login on mobile/tablet browsers via refresh token. | M | M1 |
| AUTH-006 | Forgot‑password flow with a single‑use, time‑limited (1 h) reset token. Resetting a password invalidates all sessions. | M | M1 |
| AUTH-007 | User profile: name, email, phone 1, phone 2, employee ID, timezone, language (fa/en), calendar (Jalali/Gregorian), digit style, avatar (optional). | M | M1 |
| AUTH-008 | Changing email requires verification of the new address. | M | M1 |
| AUTH-009 | Users can view and revoke their active sessions. | S | M1 |
| AUTH-010 | Account lockout / progressive delay after repeated failed logins (default: 5 failures → 15 min). | M | M1 |
| AUTH-011 | User states: ACTIVE, DEACTIVATED. Deactivated users cannot log in or receive assignments. Their historical records remain. | M | M1 |
| AUTH-012 | Users may request deletion of their personal account. Personal data is anonymized, and operational records keep an anonymized actor reference. | S | M1 |

---

## 5. ORGANIZATIONS, SUB‑ORGANIZATIONS & TENANCY (ORG)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| ORG-001 | Any verified user without a tenant membership may create an organization, becoming its **Owner** and a Manager. | M | M1 |
| ORG-002 | Organization profile: name (fa/en), logo, address, contact info, timezone, default language, default calendar, currency, 2–3 custom key‑value fields. | M | M1 |
| ORG-003 | The org profile address acts as the default root location (a root zone is created automatically). | M | M1 |
| ORG-004 | **Sub‑organizations are MVP.** An org unit may create child sub‑orgs. Maximum org tree depth: 3 (root + 2 levels). | M | M1 |
| ORG-005 | Each sub‑org has its own zones, systems, assets, cycles, templates, inventory, users, and AI data. Data of sibling sub‑orgs is mutually invisible. | M | M1 |
| ORG-006 | A user who is a member of an org unit with the **"inherit to sub‑orgs"** option holds the same role in all descendant sub‑orgs. | M | M1 |
| ORG-007 | Managers of a parent org unit can see consolidated (aggregated) dashboards and reports across descendant sub‑orgs. They can drill down only where they hold (direct or inherited) membership. | M | M4 |
| ORG-008 | Strict isolation between tenants, enforced in the application and by PostgreSQL Row‑Level Security. No feature shares data across tenants. | M | M1 |
| ORG-009 | A user belongs to exactly **one tenant** at a time, and may hold memberships in several org units of that tenant (one role per org unit). The UI provides an org‑unit switcher. | M | M1 |
| ORG-010 | Joining another tenant requires leaving the current one. The Owner must transfer ownership before leaving. | M | M1 |
| ORG-011 | Invitations: new users get an email with a secure token (expires in 14 days). Existing users are found by type‑to‑lookup on email and added after they accept. | M | M1 |
| ORG-012 | An invitation specifies org unit, role, optional zone scope, and the inherit‑to‑sub‑orgs option. | M | M1 |
| ORG-013 | Ownership transfer between Managers of the root org. Only the Owner manages subscription, billing, sub‑org creation/deletion, and AI data‑sharing consent. | M | M1 |
| ORG-014 | Tenant data export: the Owner can request a full export (structured data as JSON/CSV + files as ZIP). | S | M4 |
| ORG-015 | Tenant closure: data is retained 30 days (restorable), then permanently deleted, including files and embeddings. | S | M4 |
| ORG-016 | Org work calendar: weekly working days (default for fa locale: Saturday–Thursday, weekend Friday), shifts, and holiday list. Sub‑orgs inherit it and may override. | M | M2 |

**Acceptance (ORG):**
- A user of sub‑org A cannot read, via UI, REST, MCP, search, AI, reports, or exports, any record of sibling sub‑org B (automated isolation test suite).
- A Manager membership on the root org with "inherit" set can open any sub‑org. Without "inherit", they see only aggregated figures for sub‑orgs.
- A Free tenant cannot create a sub‑org. A Pro tenant cannot create a 6th.

---

## 6. ROLES & PERMISSIONS (RBAC)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| RBAC-001 | Platform role: **SYS_ADMIN** (platform operator; not a tenant role). | M | M1 |
| RBAC-002 | Tenant roles (one per membership): **MANAGER, REPORTER, OPERATOR, MAINTENANCE, STOREKEEPER**. | M | M1 |
| RBAC-003 | **Owner** is a flag on one root‑org Manager, not a role. | M | M1 |
| RBAC-004 | A membership may be restricted to a set of zones (**zone scope**). The user then sees and acts only on zones in scope (including sub‑zones), and on assets located there. Default: all zones. | M | M1 |
| RBAC-005 | Permissions are enforced at API level for every request, including object‑level checks, and identically for REST and MCP. | M | M1 |
| RBAC-006 | The full permission matrix is defined in `project_specification.md` §4 and is normative. | M | M1 |
| RBAC-007 | SYS_ADMIN cross‑tenant access requires an explicit "support access" session with a stated reason. It is time‑limited (default 2 h) and always audited. When configured, the tenant Owner is notified. | M | M1 |
| RBAC-008 | Custom roles / permission sets. | — | Post‑MVP |

**Role summary (informative):**

| Role | Purpose |
|---|---|
| Manager | Full setup: org units, users, zones, systems, assets, cycles, templates, inventory settings, PO approval. Approves AI‑generated content. Full ticketing and reporting. |
| Reporter | Dashboards, reports, scheduled reports, audit view. Manually advances/launches cycles. May suggest edits to AI outputs, but not approve them. |
| Operator | Raises repair tickets, logs meter readings, executes work orders assigned to them, reviews ticket outcomes. Receives AI troubleshooting hints. |
| Maintenance | Executes work orders and tickets, records labour, parts, measurements, failure codes and downtime, resets cycle baselines. Reviews and confirms AI repair steps. |
| Storekeeper | Manages parts, storerooms, stock movements, cycle counts, requisitions, POs (draft/send), and receipts. |

---

## 7. LOCALIZATION & CALENDARS (I18N)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| I18N-001 | Full UI localization in **Persian (fa)** and **English (en)**, 100% of user‑facing strings, including emails, PDFs, exports headers, error messages, and onboarding templates. | M | M1 |
| I18N-002 | Layout mirrors correctly for RTL (fa) and LTR (en). Mixed‑direction text (e.g. Persian text containing English part numbers) renders correctly in inputs, tables, and PDFs. | M | M1 |
| I18N-003 | Calendars: **Jalali (Solar Hijri)** and **Gregorian** for display and date input, selectable per user. Organization default configurable. | M | M1 |
| I18N-004 | Recurrence rules (cycles, scheduled reports) can be defined in Jalali or Gregorian terms (e.g. "1st of every Jalali month", "every Esfand 15"). | M | M2 |
| I18N-005 | Digits: display in Persian (۰–۹) or Latin (0–9) per user preference. Input accepts both and normalizes them. | M | M1 |
| I18N-006 | Search normalizes Persian/Arabic character variants (ی/ي, ک/ك, ه/ة), diacritics, and zero‑width non‑joiner (ZWNJ). | M | M4 |
| I18N-007 | Tenant‑entered master data (e.g. template names, part descriptions) may optionally hold both fa and en values. The UI shows the user's language and falls back to the other. | S | M1 |
| I18N-008 | Currency per tenant (e.g. IRR, displayed as Rial or Toman per setting, or USD/EUR). Single currency per tenant in MVP. | M | M3 |
| I18N-009 | All timestamps are stored in UTC and displayed in the user's timezone (default Asia/Tehran for fa). | M | M1 |

**Acceptance (I18N):** A Persian user with Jalali calendar and Persian digits can complete every E2E scenario with no Gregorian date, Latin digit (except in codes the user entered), or untranslated string visible. Generated PDFs render Persian correctly (shaping, RTL, font).

---

## 8. LOCATIONS / ZONES (LOC)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| LOC-001 | A zone is a location with an address. Zones are flat or form a tree of max 3 levels (zone + 2 breakdown levels, e.g. Site → Building → Floor). | M | M1 |
| LOC-002 | Zone fields: name, code, parent zone, status (ACTIVE, INACTIVE, UNDER_CONSTRUCTION, DECOMMISSIONED), address, contact, description, optional geolocation (lat/long), up to 5 custom fields. | M | M1 |
| LOC-003 | A sub‑zone inherits its parent's address unless overridden. | S | M1 |
| LOC-004 | Zone cloning: copies the zone subtree, profiles, custom fields, system links, assets (with components), meters (zeroed), cycles, template assignments, asset‑parts (BOM) links, and optional storerooms (without stock). The clone runs in the background with progress status. | M | M4 |
| LOC-005 | Zones are the unit of zone‑scoped permissions (RBAC-004). | M | M1 |

---

## 9. SYSTEMS (SYS)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| SYS-001 | Systems form max 2 levels (System → Sub‑system). | M | M1 |
| SYS-002 | A system may span multiple zones (one marked primary). | M | M1 |
| SYS-003 | Systems carry taxonomy/classification (from a tenant‑managed list) and generic technical specifications. | M | M1 |
| SYS-004 | Systems have a priority/criticality (Low/Medium/High/Critical). | M | M1 |
| SYS-005 | Cycles and work orders may target a system or sub‑system as a whole. | M | M2 |

---

## 10. ASSETS (AST)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| AST-001 | An asset is the atomic maintained item. Each asset has: **location** (zone, mandatory), optional free‑text position (e.g. "Pump room, north wall"), optional **system/sub‑system** membership, and optional **parent asset**. | M | M1 |
| AST-002 | **Physical nesting:** an asset may be on, at, or in a parent asset (e.g. agitator → tank; motor → agitator). Max nesting depth 4 (asset + 3 component levels). A component's zone always equals its parent's zone. | M | M1 |
| AST-003 | Asset fields: name (fa/en), code (unique per org unit), asset class, manufacturer, model, serial number, year, install date, purchase date, purchase cost, supplier (vendor), warranty expiry, criticality (A/B/C) and priority (Low–Critical), lifecycle status, operating state, custom/spec fields, photos, documents/manuals. | M | M1 |
| AST-004 | **Asset classes** (tenant‑managed taxonomy, e.g. "Pump › Centrifugal") provide default spec fields, default meters, default BOM, and default cycles when an asset of that class is created. | S | M1 |
| AST-005 | Lifecycle status: ACTIVE, INACTIVE (installed but idle / in storage), DECOMMISSIONED. New PM work orders and new tickets are created only for ACTIVE assets. | M | M1 |
| AST-006 | Operating state: RUNNING, RESTRICTED, STOPPED, IN_MAINTENANCE. Driven by safety flags, WOs, downtime events, and manual updates (see SAF). | M | M2 |
| AST-007 | **Move / re‑parent:** moving an asset to another zone or parent moves its components with it and is logged in asset history (from, to, who, when, reason). | M | M1 |
| AST-008 | **Install / remove events**: an asset may be removed from a parent/position (e.g. motor sent for repair) and another installed. The history shows which serial was installed where and when. | M | M3 |
| AST-009 | **Asset Bill of Materials (BOM)**: list of spare parts applicable to the asset (part, quantity, notes). It may be defined at asset‑class level and inherited. | M | M3 |
| AST-010 | QR / barcode: every asset has a stable identifier. Generate, print (single and batch label sheets), and scan with the mobile camera. | M | M1 |
| AST-011 | Soft delete only. Decommissioning a parent decommissions its components. History is preserved. | M | M1 |
| AST-012 | Managers can restore soft‑deleted (decommissioned via delete) zones, systems, and assets within 30 days. Restored entities return to ACTIVE. Cycles resume from the restore date without back‑generating missed WOs. | M | M1 |
| AST-013 | Maintenance history timeline per asset: WOs, tickets, readings, baseline resets, part consumptions, moves/installs, downtime, failure codes, AI suggestion usage, with timestamps and actors. Includes components' events when "include components" is selected. | M | M4 |
| AST-014 | Asset cost roll‑up: total labour, parts, and external cost per asset (optionally including components) for any period. | M | M3 |
| AST-015 | Warranty indicator: WOs and tickets on an asset under warranty show a warranty badge. | S | M3 |

**Acceptance (AST):** Creating "Tank T‑1" in Zone Z with a child "Agitator A‑1" and grandchild "Motor M‑1", then moving T‑1 to Zone Y, moves A‑1 and M‑1 to Y and writes three history entries. Creating a child in a different zone than its parent is rejected.

---

## 11. METERS (MTR)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| MTR-001 | An asset may have multiple meters. Types: OPERATING_HOURS, OPERATION_COUNT, DISTANCE (odometer), GENERIC (any numeric unit). | M | M2 |
| MTR-002 | Meters are **cumulative** (lifetime value). Readings must not decrease, except via a recorded **meter replacement** or **rollover** event. | M | M2 |
| MTR-003 | Operators, Maintenance, and Managers log readings (absolute value or delta). Every reading is kept with who, when, source (MANUAL, DERIVED, IMPORT, MCP, SYSTEM). | M | M2 |
| MTR-004 | Plausibility check: readings implying a rate above a configurable maximum (e.g. > 24 h per day for hours) require confirmation and are flagged. | S | M2 |
| MTR-005 | **Derived meters:** a component's meter may derive its readings from a parent asset's meter (e.g. agitator hours = tank mixer drive hours). | M | M2 |
| MTR-006 | **Baseline reset** ("counter reset" in v1): Maintenance may reset the *since‑last‑service* value used by a cycle, for the asset only or for the asset and selected components. The lifetime reading is never altered. | M | M2 |
| MTR-007 | Bulk reading entry screen (a list of meters for a zone/route). | S | M2 |

---

## 12. SAFETY FLAGS & OPERATING STATE (SAF)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| SAF-001 | Safety flags: **HOT_INSPECT** (task runs while equipment operates), **PAUSE_FOR_INSPECTION** (equipment may run but must stop briefly for the task), **STOP_UNTIL_COMPLETE** (equipment must stop until the task is complete). | M | M2 |
| SAF-002 | Flags are set on cycles, workflow/checklist items, tickets, and WOs. The WO carries the most severe flag of its items. | M | M2 |
| SAF-003 | **Upward propagation:** a STOP_UNTIL_COMPLETE on an asset sets the asset to STOPPED and marks its ancestor assets as STOPPED (default) or RESTRICTED (configurable per flag usage). Its system is shown as "impaired". PAUSE_FOR_INSPECTION marks the asset and ancestors RESTRICTED. Only safety flags can halt parents. | M | M2 |
| SAF-004 | Flags become effective when the WO starts (IN_PROGRESS), or when the deadline passes with deadline behaviour FLAG_CRITICAL_STOP. They clear when the WO is COMPLETED, or on Manager override with a mandatory reason. | M | M2 |
| SAF-005 | Operating‑state changes caused by flags automatically open and close a downtime event (reason: planned maintenance / safety stop). | M | M3 |
| SAF-006 | Flags are displayed prominently on WOs, asset pages, QR scan results, and dashboards. All flag changes are audited. | M | M2 |
| SAF-007 | Safety permits (e.g. LOTO, hot work, confined space) can be required per workflow item. The item cannot start until a Manager or authorized user records the permit number and confirms isolation. | S | M2 |

---

## 13. MAINTENANCE & INSPECTION CYCLES (PM)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| PM-001 | Cycle scope: zone, system, sub‑system, or asset. | M | M2 |
| PM-002 | Scope mode: **SELF** (one WO for the target) or **EACH_DESCENDANT** (one WO per matching descendant asset, filterable by asset class). | M | M2 |
| PM-003 | Trigger types: **calendar** (recurrence rule in Jalali or Gregorian), **meter** (every N units of a meter), **seasonal** (a yearly date window, e.g. "each autumn, Mehr 1 – Azar 30"). | M | M2 (seasonal M4) |
| PM-004 | A cycle may have multiple triggers. The first satisfied trigger generates the WO, and all triggers of the cycle restart from that WO's completion (or due point, see PM-005). | M | M2 |
| PM-005 | Scheduling basis per cycle: **FIXED** (next due counted from the previous due point) or **FLOATING** (next due counted from actual completion). | M | M2 |
| PM-006 | Generation lead time: a WO is generated N days/hours (or N meter units) before it is due. | M | M2 |
| PM-007 | Work calendar handling: when a due date falls on a non‑working day, it can be moved to the previous or next working day, or kept (per cycle). | S | M2 |
| PM-008 | Grace period / deadline per cycle. After the deadline: **FLAG_CRITICAL_STOP** (asset goes to STOPPED + critical notification) or **WAIT_UNTIL_COMPLETED** (WO stays overdue). Manager's choice per cycle. | M | M2 |
| PM-009 | Missed calendar cycles: if a due point passes without generation (e.g. system down), the next evaluation creates the WO immediately, marked overdue. Only one WO is created per missed series. Missed occurrences are not stacked. | M | M2 |
| PM-010 | Launch mode: **AUTOMATIC** (generated at 1 or 2 configured times per day, aligned to shifts) or **MANUAL** (cycle appears in a "Due for launch" list; Manager/Reporter launches). | M | M2 |
| PM-011 | Reporters and Managers may manually advance (launch early) a cycle. The next due date follows the scheduling basis. | M | M2 |
| PM-012 | Suspension: a Manager can suspend a cycle (no generation; calendar paused) and reactivate it. On reactivation the schedule resumes from the reactivation date. | M | M2 |
| PM-013 | **Inheritance:** cycles defined on zone/system/parent asset with EACH_DESCENDANT apply to descendants. A descendant may override the interval/trigger, unless the cycle is flagged **influence children** (locked). Child cycles never affect parents (except via safety flags). | M | M2 |
| PM-014 | Changes to a cycle affect only WOs generated afterwards. Existing WOs keep their snapshot. | M | M2 |
| PM-015 | **PM nesting / suppression:** cycles can be grouped so that a larger PM (e.g. annual) suppresses smaller ones (monthly, quarterly) that fall due within a tolerance window. | S | M4 |
| PM-016 | PM forecast: calendar and list view of upcoming WOs for the next N days (meter‑based dues estimated from average usage). | M | M4 |
| PM-017 | Cycles carry: code, name, description, template (checklist or workflow version), work type, priority, safety flag, estimated duration, planned parts and crafts, assignee (user/role/team). | M | M2 |
| PM-018 | Idempotency: under no circumstances may a trigger evaluation create duplicate WOs for the same due point. | M | M2 |

**Acceptance (PM):**
- A FLOATING monthly cycle completed 5 days late is next due one month after completion. A FIXED one is due one month after the original due date.
- A cycle with calendar (90 days) and meter (500 h) triggers generates exactly one WO when the first condition is met, and both counters restart.
- A Jalali rule "1st of each month" generates on 1 Farvardin, 1 Ordibehesht, …, including 31‑day and 29/30‑day months correctly.

---

## 14. CHECKLISTS & WORKFLOWS (WF)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| WF-001 | Each cycle is assigned either a checklist or a workflow. | M | M2 |
| WF-002 | Codes: auto‑generated, user‑modifiable, unique per org unit. | M | M2 |
| WF-003 | Every item is stored separately and is full‑text searchable. | M | M2 |
| WF-004 | Checklist: flat list. Item result: INSPECTED, PASS, FAIL (plus N/A if the item permits it). | M | M2 |
| WF-005 | Workflow: tasks with predecessors (sequential). | M | M2 |
| WF-006 | Workflow **parallel branches** (AND split / AND join). | M | M4 |
| WF-007 | Workflow **conditional branches** (if‑then‑else) based on measurement values or outcomes of previous tasks (e.g. "if bearing temperature > 80 °C then run 'cooling check' branch"). | M | M4 |
| WF-008 | **Versioning:** templates have versions (DRAFT → PUBLISHED → RETIRED). Only published versions can be assigned. Each WO references the exact version used. | M | M4 (M2: single implicit version) |
| WF-009 | Measurements per item: NUMERIC (unit, min, max), TEXT, BOOLEAN. | M | M2 |
| WF-010 | **Automatic pass/fail:** numeric measurements are compared to thresholds and the item result is set automatically; the executor may override with a reason. | M | M2 |
| WF-011 | Templates are org‑unit scoped. They are never shared across tenants. Within a tenant, a root‑org template may be marked "available to sub‑orgs" (read‑only, copyable). | M | M2 |
| WF-012 | "Save as template" from a completed WO (clones steps, planned parts, and crafts into a new DRAFT template). | M | M4 |
| WF-013 | Work item fields and which are mandatory are defined in `project_specification.md` §12.4. Only a minimal set is mandatory. | M | M2 |

---

## 15. WORK ORDERS (WO)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| WO-001 | Work types: PREVENTIVE, INSPECTION, CORRECTIVE, EMERGENCY, PREDICTIVE (manual in MVP), PROJECT/MODIFICATION. | M | M2 |
| WO-002 | Sources: cycle (automatic/manual launch), ticket conversion, manual creation by Manager, QR quick‑create, MCP. | M | M2 |
| WO-003 | Unique, human‑readable WO number per org unit (e.g. `WO-1405-000123`, with prefix and year per org calendar). | M | M2 |
| WO-004 | A WO holds a snapshot of the template version at generation. Later template changes never alter existing WOs. | M | M2 |
| WO-005 | Dates: issue, planned start, due (deadline), actual start, finish, stop (for halted work). | M | M2 |
| WO-006 | Status model (normative in spec §13): OPEN, ACKNOWLEDGED, IN_PROGRESS, ON_HOLD, SNOOZED, COMPLETED, CLOSED, REJECTED, CANCELLED. **Overdue** is a derived flag, not a status. | M | M2 |
| WO-007 | Acknowledgement is automatic when an assignee first opens the WO (idempotent; first‑view timestamp stored). | M | M2 |
| WO-008 | Rejection requires a reason and returns the WO to the Manager for reassignment or cancellation. | M | M2 |
| WO-009 | Snooze: 1 h, 6 h, 12 h, 1 d, 3 d, 6 d, with mandatory reason. It cannot extend beyond the deadline for STOP_UNTIL_COMPLETE WOs. | M | M2 |
| WO-010 | On hold with reason code (waiting for parts, waiting for permit, waiting for shutdown, waiting for vendor, other). | M | M2 |
| WO-011 | Assignment to a user, a role pool, or a team (crew). Multiple assignees allowed; one lead. | M | M2 |
| WO-012 | Completion rules: all mandatory items must have a result. Failed items require a comment. The Manager may enable per template: "QC sign‑off required" (moves COMPLETED → CLOSED only after reviewer approval). | M | M2 |
| WO-013 | Follow‑up: from a failed item or on completion, the executor can raise a follow‑up corrective WO or ticket, linked to the source WO. | M | M3 |
| WO-014 | Planned parts on a WO create stock reservations. Actual parts are issued from stock to the WO (see INV). | M | M3 |
| WO-015 | Labour entries, external service costs, and parts costs roll up into WO cost. | M | M3 |
| WO-016 | Digital signature (drawn signature + authenticated user + timestamp + content hash) where required. | M | M2 |
| WO-017 | Threaded comments with @mentions and image attachments, separate from formal results. | M | M2 |
| WO-018 | Calendar/Gantt planning view and backlog list (filter by zone, craft, assignee, work type, priority). | M | M4 |

---

## 16. LABOUR & COSTS (LAB)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| LAB-001 | Crafts/skills list (e.g. electrician, mechanic) with a default hourly rate. A user may have several crafts and an optional personal rate. | M | M2 |
| LAB-002 | Teams (crews) of users. | S | M2 |
| LAB-003 | Labour entries on WOs and tickets: user, craft, start/end or duration, regular/overtime. Timer start/stop on mobile. | M | M2 |
| LAB-004 | External service cost lines on WOs (vendor, description, amount, optional PO link). | M | M3 |
| LAB-005 | Certifications per user with expiry. Assigning a WO item that requires a certification to a user without a valid one shows a warning. | S | M2 |

---

## 17. REPAIR TICKETS (TKT)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| TKT-001 | Operators and Managers create tickets for an asset (or a zone/system when the asset is unknown). | M | M3 |
| TKT-002 | Mandatory: target, description, priority (LOW, MEDIUM, HIGH, CRITICAL). Optional: photos, observed symptom (failure‑code "problem" level), whether the asset is currently stopped. | M | M3 |
| TKT-003 | Overdue tenants cannot create new tickets (COM-008). | M | M3 |
| TKT-004 | New tickets go to the **Maintenance Pool**. Maintenance users claim them, or a Manager assigns them. Assignment changes are audited. | M | M3 |
| TKT-005 | 5‑step flow: (1) issued → (2) maintenance checks/works → (3) maintenance submits report → (4) issuer reviews → (5) issuer accepts & closes, or returns feedback. | M | M3 |
| TKT-006 | Steps 3–4 may loop **at most 3 times**. After the 3rd rejection the ticket becomes ESCALATED_TO_MANAGER. The Manager then force‑closes, requires a new ticket, or mandates additional action (one extra loop). | M | M3 |
| TKT-007 | **Optional conversion to a corrective WO** by Maintenance or Manager. The ticket keeps a link. When the WO completes, the WO completion notes become the ticket report (step 3) automatically, and the issuer review proceeds as usual. | M | M3 |
| TKT-008 | Report section: work done, failure codes (problem/cause/action), labour, parts used, downtime. | M | M3 |
| TKT-009 | SLA targets per priority (response time and resolution time, configurable per org unit). Breaches are flagged and notified. | M | M3 |
| TKT-010 | Reporting a ticket with "asset is stopped" opens a downtime event (unplanned). | M | M3 |
| TKT-011 | Duplicate hint: when creating a ticket on an asset with open tickets, the open tickets are shown. | S | M3 |
| TKT-012 | AI troubleshooting copilot suggestions on ticket open (see AI‑005). | M | M5 |

---

## 18. RELIABILITY: FAILURE CODES & DOWNTIME (REL)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| REL-001 | Failure code hierarchy: Problem → Cause → Action, optionally bound to asset classes. The platform ships a default set (ISO 14224‑inspired) in fa and en; tenants may edit it. | M | M3 |
| REL-002 | Corrective and emergency WOs, and ticket reports, require at least a problem code on completion (configurable). | M | M3 |
| REL-003 | Downtime events per asset: start, end, type (PLANNED / UNPLANNED), reason, linked WO/ticket. Created automatically (SAF‑005, TKT‑010) or manually. | M | M3 |
| REL-004 | KPIs: MTBF, MTTR, availability per asset/class/system (formulas in spec §20). | M | M4 |

---

## 19. INVENTORY (INV)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| INV-001 | **Part master:** part number (SKU), name (fa/en), description, category, unit of measure, manufacturer, manufacturer part number, alternates/substitutes, criticality, stocked / non‑stocked, tracking mode (NONE, LOT, SERIAL), image, barcode, default vendor(s), shelf life (optional). | M | M3 |
| INV-002 | **Units of measure** with conversions (e.g. purchase in box of 10, issue in pieces). | M | M3 |
| INV-003 | **Storerooms** (belong to an org unit, located in a zone) and **bins** within storerooms. | M | M3 |
| INV-004 | **Stock balance per part per storeroom (and bin):** on hand, reserved, available = on hand − reserved, on order. | M | M3 |
| INV-005 | **Stock ledger (append‑only):** every movement is a transaction: RECEIPT, ISSUE (to WO/ticket/asset), RETURN (from WO), TRANSFER (between storerooms/bins), ADJUSTMENT (+/−, reason code), COUNT_ADJUSTMENT, SCRAP, RETURN_TO_VENDOR, OPENING_BALANCE. Balances are never edited directly. | M | M3 |
| INV-006 | **Reservations:** planned parts on a WO reserve stock at a chosen storeroom. Released on issue, WO cancellation, or manual release. | M | M3 |
| INV-007 | **Issue & return:** Storekeeper or Maintenance (if permitted) issues parts to a WO, by barcode scan or selection. Unused parts can be returned. Issues to a WO update the WO cost. | M | M3 |
| INV-008 | Negative stock is not allowed by default (configurable per org unit). | M | M3 |
| INV-009 | **Reorder policy per part per storeroom:** min, max, reorder point, reorder quantity, lead time, safety stock. **Low‑stock alerts** when available + on order ≤ reorder point. | M | M3 |
| INV-010 | **Reorder suggestions:** a list of parts to reorder with suggested quantities, convertible into a requisition or PO in one action. Fully automatic PO creation is post‑MVP. | M | M3 |
| INV-011 | **Costing:** moving weighted average cost per part per org unit. Every transaction stores its unit cost and value. | M | M3 |
| INV-012 | **Lot and serial tracking:** lot/serial captured on receipt and issue for tracked parts. Expiry date for lots. | S | M3 |
| INV-013 | **Rotables / repairables:** a serial‑tracked part can be installed as a component asset (linked to asset install/remove, AST‑008), and a removed unit can be returned to stock as "for repair" or "repaired". | S | M3 |
| INV-014 | **Cycle counts:** create a count sheet (by storeroom, bin, category, or ABC class), enter counted quantities (mobile + scan), review variances, and approve (posts COUNT_ADJUSTMENT). | M | M3 |
| INV-015 | Inventory valuation and movement reports (stock value, slow‑moving / dead stock, consumption per asset, stock‑outs). | M | M4 |
| INV-016 | ABC classification by annual consumption value. | C | M4 |
| INV-017 | Part–asset links: BOM (AST‑009) and "where used" view per part. | M | M3 |
| INV-018 | Non‑stock / direct purchases: a part or service ordered directly for a WO is charged to the WO on receipt without entering stock. | M | M3 |

**Acceptance (INV):**
- On hand at any time equals the sum of ledger quantities (verified by a nightly consistency job; mismatch = alert).
- Two concurrent issues of the last unit: exactly one succeeds when negative stock is disabled.
- Receipt of 10 units at 120 on top of 10 units at 100 gives an average cost of 110.

---

## 20. PURCHASING (PUR)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| PUR-001 | **Vendors:** name, code, contacts, address, tax/registration ID, payment terms, currency, lead time, rating (optional), status, attachments. Vendor–part catalogue (vendor part no., price, lead time). | M | M3 |
| PUR-002 | **Purchase requisition (PR):** created by Maintenance, Storekeeper, or Manager (from reorder suggestions, a WO, or manually), for stock parts, non‑stock items, or services. States: DRAFT, SUBMITTED, APPROVED, REJECTED, CONVERTED, CANCELLED. | M | M3 |
| PUR-003 | **Purchase order (PO):** created from approved PR lines or directly by Storekeeper/Manager. Lines: part/description, qty, UoM, unit price, delivery storeroom or WO (direct charge), required date. | M | M3 |
| PUR-004 | **Approval:** PO approval by Manager. Optional value thresholds per org unit (e.g. above X requires root‑org Manager). | M | M3 |
| PUR-005 | PO states: DRAFT, PENDING_APPROVAL, APPROVED, SENT, PARTIALLY_RECEIVED, RECEIVED, CLOSED, CANCELLED. | M | M3 |
| PUR-006 | PO document: printable/PDF in fa and en, with tenant logo. Sending by email to vendor is optional (uses transactional email; see NOT‑002). | M | M3 |
| PUR-007 | **Receipt:** full or partial per line, with an over‑receipt tolerance (default 0%), lot/serial capture, putaway to bin, and a receipt document. Posts RECEIPT to the ledger at PO unit price (updates average cost). | M | M3 |
| PUR-008 | Receipts of lines charged to a WO add cost to that WO and notify the WO assignee (e.g. "parts arrived"; releases ON_HOLD waiting for parts). | M | M3 |
| PUR-009 | Return to vendor from a receipt (reason, quantity). | S | M3 |
| PUR-010 | "On order" quantities are visible on part and stock screens. | M | M3 |
| PUR-011 | Invoice matching, RFQ/quotation comparison, vendor portal, budgets. | — | Post‑MVP |

---

## 21. NOTIFICATIONS & ANNOUNCEMENTS (NOT)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| NOT-001 | In‑app notification centre: bell icon, unread badge, list, read/unread, deep links. Notifications expire after 30 days. | M | M2 |
| NOT-002 | Email is used only for: auth flows (verification, reset, invitation), scheduled report delivery, and optional PO sending to vendors. No operational email/SMS notifications in MVP. | M | M1 |
| NOT-003 | Web push notifications through the PWA (opt‑in per user/device). | C | M4 |
| NOT-004 | Users can mute notification categories (except safety‑critical ones). | S | M2 |
| NOT-005 | Event catalogue (recipients defined in spec §19) includes: WO assigned, due soon, overdue, snooze expired, returned/rejected; ticket new in pool, claimed/assigned, report submitted, feedback, escalated, SLA breach; safety stop activated; low stock; PR/PO awaiting approval, PO approved, parts received; cycle failure; import/export/clone finished; AI job finished; MCP action awaiting confirmation; announcement posted. | M | M2–M5 |
| NOT-006 | Announcements: Managers post broadcast messages to an org unit (optionally including sub‑orgs), with optional expiry and "must acknowledge" option. | M | M4 |
| NOT-007 | Task status centre: users see their background jobs (imports, exports, clones, AI jobs, reports) with progress and results. | M | M4 |

---

## 22. REPORTING & DASHBOARDS (RPT)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| RPT-001 | Personal dashboard (all roles): my new / active / overdue WOs, my tickets, role shortcuts. | M | M2 |
| RPT-002 | Manager/Reporter dashboards with filters (date range, org unit, zone, system, asset class, work type, priority, assignee). | M | M4 |
| RPT-003 | KPIs (formulas in spec §20): WOs by status, overdue WOs, PM compliance %, planned vs unplanned ratio, backlog (count and estimated hours), WO ageing, open tickets, escalated tickets, SLA compliance, MTBF, MTTR, availability, downtime by reason, maintenance cost by asset/system/zone/type, labour hours by craft, inventory value, stock‑outs, low‑stock items, open POs, safety‑flag incidents. | M | M4 |
| RPT-004 | Consolidated dashboards across sub‑orgs for parent org managers (ORG‑007). | M | M4 |
| RPT-005 | Export of any list/report to CSV and XLSX. PDF for summary reports (fa/en). | M | M4 |
| RPT-006 | Scheduled reports: weekly/monthly (Jalali or Gregorian) summary PDFs, delivered by email to selected org members and to the notification centre. | M | M4 |

---

## 23. SEARCH, COLLABORATION & TIMELINE (COL)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| COL-001 | Global search in header: assets (name, code, serial), zones, systems, WO numbers, ticket numbers, parts (SKU, name, manufacturer part no.), vendors, POs, templates and template items. Results respect permissions and zone scope. | M | M4 |
| COL-002 | Manual content search: semantic + keyword search inside ingested manuals, returning document/page hits. | M | M5 |
| COL-003 | Filters, sorting, and saved views on all list pages. | M | M2 |
| COL-004 | Comment threads with @mentions and image attachments on WOs, tickets, assets, POs. | M | M2 |
| COL-005 | Asset timeline (AST‑013). | M | M4 |

---

## 24. FILES & DOCUMENTS (FILE)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| FILE-001 | Allowed types: JPEG, PNG, WEBP, HEIC (converted), PDF, TXT, DOCX, XLSX. Max 10 MB default (configurable per tier; manuals up to 50 MB). Extension + MIME + magic‑byte validation; executables blocked. | M | M1 |
| FILE-002 | Attach to: zones, systems, assets, asset classes, parts, vendors, WOs, WO items, tickets, POs, comments. | M | M1 |
| FILE-003 | Document types: MANUAL, DRAWING, CERTIFICATE, PHOTO, DATASHEET, OTHER. Documents may be linked to multiple assets (e.g. one manual for 20 identical pumps) and to asset classes. | M | M1 |
| FILE-004 | Image compression/thumbnailing on upload. | S | M1 |
| FILE-005 | Storage per tier (quota) with usage display. | S | M1 |
| FILE-006 | Manuals (PDF/TXT/DOCX) are automatically ingested for AI retrieval when AI is enabled (see AI‑004). Scanned PDFs are OCR'd (fa + en). | M | M5 |

---

## 25. IMPORT, EXPORT & ONBOARDING (IMP)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| IMP-001 | Import via CSV/XLSX with downloadable templates (fa/en headers): zones, systems, asset classes, assets (with parent references), meters and opening readings, cycles, checklists, sequential workflows, parts, storerooms/bins, opening stock balances, vendors, vendor price lists, users (as invitations), failure codes. | M | M4 |
| IMP-002 | Import runs as: upload → validate → preview (row‑level errors) → commit (all‑or‑nothing per file) → result report. | M | M4 |
| IMP-003 | Exports of lists to CSV/XLSX (RPT‑005) and tenant full export (ORG‑014). | M | M4 |
| IMP-004 | Industry starter templates at org creation (fa and en): **Facility Management** (HVAC, elevators, lighting, fire safety), **Fleet** (vehicles, distance meters), **Manufacturing Line** (conveyors, motors, pumps, tanks with agitators). Each includes zones, systems, asset classes, sample assets, cycles, checklists, parts, and failure codes. | M | M4 |
| IMP-005 | Guided setup wizard for first‑time managers (adapt template, invite users, create first cycle), and contextual tooltips on key screens. | M | M4 |

---

## 26. AI COPILOT (AI)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| AI-001 | Every AI output is a **draft/suggestion**. Nothing AI‑generated becomes active (template published, WO created, plan applied) without explicit human approval by an authorized role. | M | M5 |
| AI-002 | **Checklist generation** from a text prompt (fa or en) and optional asset class / asset context. | M | M5 |
| AI-003 | **Workflow generation**, including suggested parallel groups and conditional rules. | M | M5 |
| AI-004 | **Manual assistant (RAG):** chat grounded in manuals linked to the asset / asset class, with citations (document + page). If nothing relevant is found it says so, and never invents specifications. | M | M5 |
| AI-005 | **Troubleshooting copilot:** on ticket open (and on demand on corrective WOs), suggest probable causes and repair steps from manuals + the tenant's historical WOs/failure codes for similar assets. Maintenance edits and approves the action plan. | M | M5 |
| AI-006 | **Auto‑fill:** suggest WO description, planned parts (from BOM/history), estimated duration, crafts, and failure codes based on similar past work. | M | M5 |
| AI-007 | **Confidence & rationale:** every suggestion shows a confidence level (High/Medium/Low with 0–100 score) computed as defined in spec §25.3, and a short rationale ("based on 4 similar WOs on Centrifugal Pumps", "manual X p.42"). | M | M5 |
| AI-008 | Human actions on suggestions (accept, edit, reject + optional reason) are recorded (see AIT). | M | M5 |
| AI-009 | Reporters may attach suggested edits to AI drafts. Only Managers approve templates, and only Maintenance/Managers approve repair plans. | M | M5 |
| AI-010 | Provider abstraction: OpenAI‑compatible APIs, Anthropic API, and self‑hosted models (Ollama/vLLM). Chosen per platform, overridable per tenant (Ultimate). | M | M5 |
| AI-011 | **Fallback mode** when the provider is unavailable: retrieval‑only answers (relevant manual passages without generation), and template suggestions assembled from the tenant's similar existing templates. Clearly labelled "fallback". | M | M5 |
| AI-012 | **Privacy for external providers:** prompts exclude tenant identifiers, user personal data, and addresses. Only equipment/maintenance context is sent. Tenants can require self‑hosted models only (privacy mode). | M | M5 |
| AI-013 | AI usage quotas per tier (tokens/requests per month), per‑user rate limits, and a usage view for Managers. | M | M5 |
| AI-014 | Tenants can disable AI entirely. | M | M5 |
| AI-015 | AI features support fa and en input and respond in the user's language. | M | M5 |
| AI-016 | Quality measurement: acceptance rate, edit distance, and citation coverage are tracked per feature and model version (admin dashboard). | S | M5 |

---

## 27. AI TRAINING DATA (AIT)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| AIT-001 | Every AI interaction is logged: org unit, user, timestamp, feature, model/provider/version, prompt, retrieved context references, raw output, human‑edited final version, decision (approved/edited/rejected), rejection reason, confidence, fallback flag. | M | M5 |
| AIT-002 | **Per‑tenant training (default):** each tenant's interaction data forms a tenant‑private dataset. It may be used only to improve models or adapters (e.g. LoRA) that serve **that tenant only**. | M | M5 |
| AIT-003 | **Broad (cross‑tenant) training** may use only data that has passed the **anonymization pipeline**, which removes or generalizes all identifying content (names, codes, serials, addresses, phone numbers, emails, vendor names, tenant‑specific terms, free‑text PII in fa and en). Output records must be **non‑addressable**: they cannot be traced to a tenant, site, asset, or person. | M | M5 |
| AIT-004 | Tenant setting **"Contribute anonymized data to platform models"**, controlled by the Owner. The default value is a platform setting, disclosed in the terms of service. | M | M5 |
| AIT-005 | Managers can view and correct their tenant's training log entries (e.g. mark as bad example, exclude). | M | M5 |
| AIT-006 | SYS_ADMIN exports: per‑tenant datasets (only with that tenant's contract permission) and the anonymized broad dataset, in JSONL/Parquet. Every export is audited. | M | M5 |
| AIT-007 | Anonymized broad records are stored separately from tenant data, without any key back to the source. Deleting a tenant removes its per‑tenant dataset. Already anonymized broad records are not affected (disclosed in terms). | M | M5 |
| AIT-008 | Anonymization quality gate: automated PII detection on output plus a periodic human‑reviewed sample. A batch with detected residual PII is rejected. | M | M5 |

---

## 28. MCP – EXTERNAL AI OPERABILITY (MCP)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| MCP-001 | An MCP server exposes resources (read), tools (actions), and prompts covering assets, meters, cycles, templates, WOs, tickets, inventory, purchasing, reports, and the AI assistant. | M | M5 |
| MCP-002 | Transports: stdio and Streamable HTTP. | M | M5 |
| MCP-003 | Authentication: user JWT or **scoped API key**. Managers create, rotate, and revoke API keys bound to one org unit, one role, optional zone scope, optional read‑only flag, and an expiry. | M | M5 |
| MCP-004 | Same RBAC, tenancy, and validation as REST (shared domain layer). SYS_ADMIN is never available through MCP. | M | M5 |
| MCP-005 | **Confirmation gates** (human approval in the UI) for: STOP_UNTIL_COMPLETE flags, decommission, zone clone, CRITICAL tickets, PO approval, stock adjustments above threshold, bulk operations > 10 records. Pending actions appear in an "AI actions awaiting approval" list and expire after 24 h. | M | M5 |
| MCP-006 | Dry‑run on every write tool. | M | M5 |
| MCP-007 | Rate limits and quotas per tier and per key. Operation ceiling: 50 WOs / 50 tickets per key per hour (configurable). | M | M5 |
| MCP-008 | An agent may escalate but never clear or downgrade a human‑set STOP_UNTIL_COMPLETE flag. | M | M5 |
| MCP-009 | Undo: an agent may revert its own recent operations (default within 5 min) via **compensating actions**, provided no human has acted on the records since. The audit log is never modified. | S | M5 |
| MCP-010 | All MCP calls are audited with actor type MCP_AGENT and key ID. Managers see an "AI Activity Log". | M | M5 |
| MCP-011 | Free tier: read‑only MCP. | M | M5 |

---

## 29. MOBILE, QR & OFFLINE (MOB)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| MOB-001 | Fully responsive UI for phone, tablet, and desktop. | M | M1 |
| MOB-002 | Installable **PWA**. | M | M4 |
| MOB-003 | QR scan opens the asset: profile, operating state and flags, open WOs/tickets, history, manuals, and quick actions (create ticket, log reading, start assigned WO, ask manual assistant). | M | M1 (actions M2–M5) |
| MOB-004 | Mobile quick actions with large touch targets: Complete WO item, Add reading, Scan QR, Issue part, Start/stop labour timer. | M | M2 |
| MOB-005 | **Limited offline:** assigned WOs (with checklists and manuals already opened) are cached. Meter readings, item results, measurements, comments, and photos entered offline are queued and synced when online, with conflict reporting. Creating tickets, stock transactions, and approvals require connectivity. | S | M4 |
| MOB-006 | Camera capture for photos directly into WO items and tickets. | M | M2 |

---

## 30. AUDIT (AUD)

| ID | Requirement | Pri | MS |
|---|---|---|---|
| AUD-001 | Immutable, append‑only audit log of critical changes (catalogue in spec §29): auth events, memberships/roles, org units, assets and moves, cycles, WO and ticket state changes, safety flags, meter corrections and baseline resets, stock transactions and adjustments, PR/PO approvals, AI approvals/rejections, MCP actions, SYS_ADMIN support access, exports. | M | M1 |
| AUD-002 | Fields: timestamp (UTC), tenant/org unit, actor (user / MCP key / system), actor role, action, entity type & ID, previous state, new state, IP, user agent, request ID. | M | M1 |
| AUD-003 | Audit UI for Managers and Reporters: filter by date, user, entity, action; export CSV. | M | M4 |
| AUD-004 | Retention: default 7 years (configurable per tenant, minimum 1 year). | M | M1 |

---

## 31. NON‑FUNCTIONAL REQUIREMENTS (NFR)

| ID | Requirement | Pri |
|---|---|---|
| NFR-001 | **Performance:** API p95 ≤ 300 ms for reads and ≤ 600 ms for writes at target load (excluding AI, exports, imports). | M |
| NFR-002 | **Frontend:** Largest Contentful Paint ≤ 2.5 s on a mid‑range phone over 4G. Initial JS bundle ≤ 350 KB gzipped. | M |
| NFR-003 | **Scale targets (SaaS, MVP):** 1,000 tenants; per tenant up to 50,000 assets, 200,000 parts‑stock rows, 500,000 WOs, 300 concurrent users. | M |
| NFR-004 | **Scheduler:** every due cycle is evaluated within 10 minutes of its evaluation slot. 100,000 active cycles are evaluated in < 10 minutes. | M |
| NFR-005 | **AI latency:** RAG first token ≤ 4 s p95 (external provider). Checklist generation ≤ 30 s p95. | S |
| NFR-006 | **Availability (SaaS):** 99.5% monthly, excluding announced maintenance. | M |
| NFR-007 | **Backup & recovery:** RPO ≤ 15 min (continuous WAL archiving), RTO ≤ 4 h. Restore tested quarterly. | M |
| NFR-008 | **Retention:** notifications 30 days; soft‑deleted restore window 30 days; generated exports 7 days; AI logs 2 years (training datasets per AIT); audit per AUD‑004. | M |
| NFR-009 | **Browsers:** latest 2 versions of Chrome, Edge, Firefox, Safari; iOS Safari 16+; Android Chrome. | M |
| NFR-010 | **Accessibility:** WCAG 2.1 AA for core flows, in both RTL and LTR. | S |
| NFR-011 | **Security baseline:** OWASP ASVS Level 2. | M |
| NFR-012 | **Privacy:** tenant data export & deletion (ORG‑014/015), personal data minimization, and a DPA/terms that describe AI data usage (AIT). | M |
| NFR-013 | **Observability:** structured JSON logs with request ID, tenant and user IDs; metrics; error tracking (Sentry‑compatible); health endpoints. | M |
| NFR-014 | **Maintainability:** ≥ 80% unit‑test coverage for domain services. Every requirement ID with priority M has at least one automated acceptance test. | M |
| NFR-015 | **API:** versioned REST (`/api/v1`) with OpenAPI docs. Breaking changes only in a new version. | M |
| NFR-016 | **Self‑hosting:** single‑server Docker Compose install in ≤ 30 minutes following the installation guide. | M |

---

## 32. SECURITY (SEC)

| ID | Requirement | Pri |
|---|---|---|
| SEC-001 | HTTPS only in production. HSTS enabled. Secure, HttpOnly, SameSite cookies for refresh tokens. CSRF protection on cookie‑based endpoints. | M |
| SEC-002 | Password hashing with Argon2id. | M |
| SEC-003 | Rate limiting: default 100 req/min per user and per IP (configurable). Stricter limits on login, reset, invitations, uploads, AI, MCP. | M |
| SEC-004 | Tenant‑scoped object storage paths. Private buckets. Short‑lived pre‑signed URLs (≤ 15 min). | M |
| SEC-005 | Antivirus scanning of uploads (ClamAV or equivalent) before files become downloadable. | S |
| SEC-006 | Content Security Policy, output encoding, and dependency vulnerability scanning in CI. | M |
| SEC-007 | Secrets only in environment/secret manager. Separate secrets per environment. | M |
| SEC-008 | Prompt‑injection mitigation for RAG: retrieved document text is treated as data. The AI cannot invoke write tools from inside the in‑app assistant. | M |

---

## 33. OPERATIONS & DEPLOYMENT (OPS)

| ID | Requirement | Pri |
|---|---|---|
| OPS-001 | Stack: Python 3.11+, **FastAPI**, SQLAlchemy, Pydantic, Alembic, Celery + Redis, PostgreSQL 15+ with pgvector, MinIO/S3, React 18 + TypeScript + Vite. | M |
| OPS-002 | Docker Compose for development and single‑server self‑hosting. Helm chart / Kubernetes manifests for SaaS production. | M |
| OPS-003 | Environment configuration via `.env` (dev/staging/prod). Feature flags for AI provider, MCP, and billing. | M |
| OPS-004 | Alembic migrations run automatically in CI/CD, and must be backward compatible for rolling deploys. | M |
| OPS-005 | Health endpoints: `/health/live`, `/health/ready` (DB, Redis, storage, AI provider status). | M |
| OPS-006 | CI: lint, type check, tests, migration check, image build, dependency and container scanning. CD to staging, and production after manual approval. | M |
| OPS-007 | Admin console (SYS_ADMIN): tenants, tiers, payment state, support access, failed background jobs, AI provider settings, dataset exports. | M |

---

## 34. POST‑MVP (EXPLICITLY DEFERRED)

- SSO/OAuth, MFA/2FA.
- Custom roles / permission sets.
- Operational email/SMS notifications (other than scheduled reports).
- Full offline mode (beyond MOB‑005).
- Native mobile apps.
- IoT / sensor integration and automatic meter feeds; condition‑based triggers from live data.
- Vision AI (image‑based ticketing, part identification).
- Automatic PO creation; RFQ; invoice matching; budgets; vendor portal.
- Asset depreciation and financial asset accounting.
- Equipment‑specific technical forms beyond class spec fields.
- Maps and GIS views (only the lat/long field is in MVP).
- Multi‑currency per tenant.
- 21 CFR Part 11–grade electronic signatures.

---

## 35. OPEN DECISIONS (WITH PROPOSED DEFAULTS)

Each item has a proposed default that the documents already assume. Confirm or change it.

| # | Decision | Proposed default |
|---|---|---|
| D1 | Licence | AGPL‑3.0 |
| D2 | Payment providers for SaaS | Provider abstraction. Initial providers to be chosen by market (e.g. an Iranian gateway for IRR, Stripe for international). |
| D3 | Default for "contribute anonymized data" (AIT‑004) | ON for Free/Pro, OFF for Ultimate, always changeable by Owner |
| D4 | Trial | 30‑day Pro trial |
| D5 | Do component assets count toward tier limit? | Yes (COM‑004) |
| D6 | Default AI provider for SaaS | External provider with self‑hosted option. Privacy mode available on Ultimate. |
| D7 | Weekend / holiday defaults for fa tenants | Friday weekend; official Iranian holiday list shipped and editable |
| D8 | Tier AI quotas (numeric) | To be set after cost modelling |
