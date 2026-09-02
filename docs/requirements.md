# PROJECT AIAMMS  
## AI‑Assisted Maintenance Management System  
### Open‑Source CMMS Web SaaS  
#### CONSOLIDATED & EXPANDED REQUIREMENTS – MVP SCOPE  

---

## 1. PROJECT PURPOSE & PHILOSOPHY

**AIAMMS** is an open‑source Computerized Maintenance Management System (CMMS) delivered as a web‑based SaaS. It enables organizations to manage:

- Users, organizations, and sub‑organizations (multi‑tenant with strict isolation).
- Hierarchical assets: Zones → Systems → Sub‑systems → Service Points / Nodes.
- Maintenance & inspection cycles, workflows (including parallel branches and conditional logic), checklists.
- Work orders, repair tickets, attachments, and inventory (spare parts).
- Advanced dashboards, scheduled reports, and full audit trails.
- **AI copilot** capabilities:
  - AI‑generated checklists and work instructions.
  - AI‑assisted troubleshooting and repair suggestions via RAG (Retrieval‑Augmented Generation) over ingested manuals.
  - **AI fills forms and suggests every configurable item** – the human (Manager/Maintenance) **reviews and approves** before activation.
  - Continuous learning: the system **logs all AI interactions, human corrections, and approvals** to produce high‑quality fine‑tuning datasets for iterative model improvement.
- MCP (Model Context Protocol) exposure of all system functions for external AI orchestration.

**Core philosophy:**  
AI is the **copilot** – it accelerates work, reduces errors, and learns from every human decision, but **never overrides** human authority.

---

## 2. CORE TECHNICAL STACK

| Layer               | Technology                                                       |
|---------------------|------------------------------------------------------------------|
| Backend language    | Python 3.11+                                                     |
| API framework       | FastAPI or Django (REST, JWT)                                    |
| Database            | PostgreSQL 15+ with **pgvector** extension                       |
| Async processing    | Celery + Redis (broker & cache)                                  |
| Web client          | React 18+ / Node.js (mobile/tablet‑responsive)                   |
| File storage        | Server disk + S3‑compatible (MinIO) for attachments & exports    |
| AI integration      | External LLM API (OpenAI/Anthropic) + local fallback mode        |
| AI training pipeline| Data collection service + export scripts for fine‑tuning (LoRA / QLoRA) |
| Deployment          | Docker Compose (dev) + Kubernetes‑ready manifests (prod)         |
| Migrations          | Alembic                                                          |
| Monitoring          | Structured JSON logs + health check endpoint + Sentry integration|

---

## 3. USER ACCOUNTS & SIGNUP

### 3.1 Self‑Service Registration
- Email + password (min 8 chars, 1 uppercase, 1 number).
- Email verification required (time‑limited token).
- **Post‑MVP**: SSO/OAuth, MFA/2FA.

### 3.2 User Profile
- Name, Email, Phone 1, Phone 2, Employee ID, Timezone.
- Profile picture (optional).

### 3.3 Organization & Sub‑Organization Membership
- A user belongs to **one primary organization** at a time.
- **Sub‑organizations** (nested tenants) are supported in MVP:
  - Parent org can create child orgs with separate data isolation.
  - Users can be shared across parent/child via invitation with inherited roles.
  - Sub‑orgs have their own tier limits (see 4.7) but can be centrally managed.

### 3.4 User Deactivation
- Deactivated users: no new assignments, no role changes, historical records remain.

### 3.5 System Administrator (Platform Level)
- Override all limitations, delete users, reset passwords, view all orgs (debug mode).
- Manage platform‑wide AI model settings and fine‑tuning data exports.

### 3.6 Password Recovery
- “Forgot Password” flow with secure, time‑limited email token.

---

## 4. ORGANIZATION & SUB‑ORGANIZATION MANAGEMENT

### 4.1 Organization Creation
- Any verified user may create an organization (tenant).

### 4.2 Strict Data Isolation
- **Row‑Level Security (RLS)** in PostgreSQL ensures no cross‑org data leakage.

### 4.3 Sub‑Organizations (MVP)
- Hierarchical tenant structure (max depth 3).
- Parent org can view aggregated reports across sub‑orgs (with permission).
- Each sub‑org has its own zones, systems, users, and AI training data (isolated by default).

### 4.4 Organization Profile
- Logo, contact info, 2–3 custom K‑V fields.
- Base address also serves as a “Zone” for default location.

### 4.5 Zone Address & Contact
- Each zone must have address and contact details.

### 4.6 Invitations
- Email with secure token (expires in 14 days) for new users.
- Direct lookup‑and‑add for existing users.
- Invitations can be scoped to sub‑organizations.

### 4.7 Subscription / Tier Limits (Applies to Service Points Only)
| Tier      | Max Nodes | Sub‑orgs allowed |
|-----------|-----------|------------------|
| Free      | 100       | 0                |
| Pro       | 1,000     | up to 5          |
| Ultimate  | Unlimited | unlimited        |

### 4.8 Overdue Payment Behavior
- Overdue orgs **cannot send repair tickets**; all other features (including AI suggestions) remain active.

---

## 5. ROLE MANAGEMENT (Organization & Sub‑Org Level)

| Role       | Permissions                                                                                                                                 |
|------------|---------------------------------------------------------------------------------------------------------------------------------------------|
| **Manager**| Full setup (Zones, Systems, Nodes, Cycles, Workflows, Inventory).<br>Set auto/manual launch modes.<br>Full ticketing & reporting.<br>**Approve AI‑generated checklists/workflows before they go live.**<br>View and edit all AI training logs for their org. |
| **Reporter**| Access advanced dashboards, scheduled reports, manually advance cycles. Can **suggest edits** to AI outputs (not approve).                    |
| **Operator**| Issue repair tickets, log counter readings, execute assigned work.<br>**Receive AI‑assisted troubleshooting suggestions** for active tickets. |
| **Maintenance**| Receive WO/tickets, perform work, submit feedback, reset counters.<br>**Review AI‑generated repair steps** and edit/confirm them before closing a ticket. |

---

## 6. ASSET HIERARCHY (INCLUDING SUB‑ORGS)

- **Maximum depth**: 6 levels (`Org → Sub‑Org → Zone → System → Sub‑system → Node`).
- **Zones**: Flat or 2‑level tree. Status (Active/Inactive/Under construction/Decommissioned), up to 5 custom fields, required address/contact.
- **Zone cloning**: Full tree + profiles + cycles + workflows + checklists + inventory links.
- **Systems & Sub‑systems**: Max 2 levels. Systems may span zones.
- **Classification & Technical Specifications**: Taxonomy support; generic spec fields (post‑MVP: equipment‑specific forms).
- **Prioritization**: All assets support Priority (Low/Medium/High/Critical).
- **Barcode / QR Code**: Generate, print, scan (read via mobile camera).
- **Soft Delete**: Restrict hard deletion. Soft‑delete = Decommissioned/Archived. Parent decommission → children inherit status and become inaccessible for new WOs. **Managers can restore soft‑deleted entities within 30 days** (restoration resets status to Active).

---

## 7. SERVICE POINTS / NODES / EQUIPMENT (MVP WITH INVENTORY)

### 7.1 Definition
Atomic maintenance unit; may halt parent structure via safety flags.

### 7.2 Profile & Relationships
- Profile, maintenance history, manuals/attachments, assigned cycles, **spare parts list**.
- Inventory integration (MVP):
  - **Parts table** (name, SKU, manufacturer, min/max stock, unit cost).
  - **Node‑Parts relationship** (which parts are used where).
  - **Work Order‑Parts usage** (consume quantities, track remaining stock).
  - Low‑stock alerts (configurable thresholds).

### 7.3 Counters
- Operation hours, operation count (configurable, may inherit from parent).
- Maintenance users can reset counters (node only, or recursively).

### 7.4 Attachments
- Photos, PDF, TXT, DOCX (max 10 MB, MIME validation).

### 7.5 Lifecycle Status
- **Active**, **In Maintenance**, **Decommissioned**.
- WOs/tickets can be created **only for Active** nodes.

### 7.6 AI Manual Ingestion (RAG)
- PDFs attached to nodes are **automatically parsed, chunked, and embedded** into pgvector.
- Strictly isolated by `organization_id` (and `sub_org_id`).

---

## 8. MAINTENANCE & INSPECTION CYCLES (INCLUDING SEASONAL)

### 8.1 Scope
- Zone, System, Sub‑system, Node.

### 8.2 Trigger Types
- **Number of operations**, **hours of operation**, **calendar (cron)**, **seasonal** (new – e.g., “every winter solstice” or “quarterly based on meteorological seasons” with date ranges).

### 8.3 Multiple Triggers
- First satisfied trigger wins.

### 8.4 Grace Period / Deadline
- After deadline: flag as Critical Stop or wait until completion (manager’s choice).

### 8.5 Missed Calendar Cycles
- If a calendar cycle passes its deadline without triggering, the **next system evaluation** creates an “Overdue” Work Order immediately.

### 8.6 Cycle Suspension
- Managers can suspend cycles (no WO generation, calendar pauses).

---

## 9. CYCLE INHERITANCE

- **Top‑down** (org → sub‑org → zone → …). Operation hours/counts inherit unless overridden.
- If flagged “Influence children”, child nodes **cannot override** the cycle.
- Child cycles **do not influence parents** (except safety flags).
- Changes to parent cycles apply only to **new instances** – existing WOs are not retroactively changed.

---

## 10. WORKFLOWS & CHECKLISTS (WITH PARALLEL BRANCHES & CONDITIONAL LOGIC – MVP)

### 10.1 Assignment
- Each cycle can be assigned a workflow (task sequence) or a checklist (inspection).

### 10.2 Unique Coding
- Auto‑generated, user‑modifiable, must remain unique per org.

### 10.3 Searchability
- Each item (task/inspection step) stored separately and full‑text searchable.

### 10.4 Checklist
- Inspection only. Result: Inspected, Pass, Fail.

### 10.5 Workflow (MVP Extended)
- **Task states**: Task, Started, Completed, Failed, Pending, Performed by.
- **Parallel branches**: Tasks can run concurrently (AND splits/joins).
- **Conditional logic**: If‑then‑else branches based on measurement values or previous task outcomes (e.g., “If temperature > 80°C, run cooling check branch”).
- **Versioning**: Workflows are versioned; WOs reference a specific version.

### 10.6 No Cross‑Org Sharing
- Workflows/checklists are strictly org‑isolated.

### 10.7 AI Copilot – Checklist & Workflow Generation
- Manager clicks “AI Generate” in the creator form.
- **Prompt** (e.g., “Monthly maintenance for 500kVA Diesel Generator”).
- AI returns **structured suggestions**: activity descriptions, measurement units, min/max thresholds, **recommended parallel groups**, and **conditional rules**.
- **Human review & approval** is mandatory – the AI output is shown side‑by‑side with an edit form; the manager edits, then clicks “Approve & Save” to create the version.
- If rejected, the manager provides feedback (stored as training data).

---

## 11. WORK ITEMS / ACTIVITY ITEMS

Each item stored separately. Core fields:

- Activity number, Planned/Assigned/Deadline/Started/Closed date/time.
- Description, Status (Successful, Failed, Halted, Pending), Predecessor(s).
- Priority, Estimated/Actual duration, Assigned to, Required skills/certifications/tools/parts.
- Safety permit, Risk level, Location override, Attachments, Digital signature.
- Notes/Comments, Cost, Downtime impact, Linked ticket ID, Completion %, Quality check by.
- **Measurements**: Numeric, Text, or Boolean (Pass/Fail) with min/max thresholds.
- **Automatic pass/fail** is now **MVP** (system compares numeric measurements against thresholds).

---

## 12. WORK ORDERS

### 12.1 Creation
- Cycle triggers WO = a copy of the workflow version with execution dates.

### 12.2 Identification
- Unique WO number (auto‑generated, human‑readable).

### 12.3 Dates
- Issue, Start, Finish, Stop date/time.

### 12.4 Acknowledgment
- Automatic on user view.

### 12.5 Rejection
- Requires description/reason.

### 12.6 Snooze
- Allowed: 1h, 6h, 12h, 1d, 3d, 6d with mandatory reason.

### 12.7 Work Order Templates (MVP)
- After completing a WO, a Manager can “Save as Template” – this clones the workflow, checklist, and assigned parts into a reusable template for future cycles.

---

## 13. SAFETY / OPERATIONAL FLAGS

| Flag               | Meaning                                                          |
|--------------------|------------------------------------------------------------------|
| Hot inspect        | Executed while equipment is running.                             |
| Pause for inspection | Continue running but stop shortly.                             |
| Stop until complete | Halt operation until the task is done.                          |

- Service point may halt parent structure only via these flags.

---

## 14. REPAIR TICKETING SYSTEM (MVP)

### 14.1 Creation
- Operators and Managers create tickets → routed to Maintenance pool.

### 14.2 Sections
- Report section (issue description, photos), Feedback section (resolution notes).

### 14.3 Circulation Flow
1. Issue → 2. Maintenance check/do → 3. Maintenance reports → 4. Issuer reviews → 5. Accept/Feedback.  
- Loops repeat up to 3 times; if unresolved, escalates to Manager.

### 14.4 Priority & Severity
- Low, Medium, High, Critical – required on creation.

### 14.5 Assignment Logic
- Unassigned tickets appear in “Maintenance Pool”.  
- Maintenance users Claim, or Manager assigns directly.

### 14.6 Overdue Org Restriction
- Overdue orgs cannot send new tickets.

### 14.7 AI Troubleshooting Copilot
- When a ticket is opened, the system **automatically suggests** probable causes and repair steps (RAG over manuals + historical WO data).
- Maintenance user reviews the suggestions, can **edit** them, and **approves** the final action plan before executing.
- All suggestions and edits are logged for model fine‑tuning.

---

## 15. MAINTENANCE SCHEDULES & LAUNCH MODES

- Manager sets auto (1–2x per day) or manual.
- Reporter can manually advance cycles.

---

## 16. REPORTING & DASHBOARDS

### 16.1 Access
- Manager and Reporter.

### 16.2 Core Dashboards
- **Live counters**: New/Active WOs, overdue tickets, low‑stock alerts.
- **Filtering & export** (CSV/PDF) by date, node, status, priority.
- **Maintenance history timeline** per node (see 19).

### 16.3 Scheduled Reports (MVP)
- Manager can schedule weekly/monthly summary reports (PDF) delivered to their email or downloadable from the notification center.

---

## 17. NOTIFICATIONS & ANNOUNCEMENTS

### 17.1 Channels
- In‑app only (no email/SMS in MVP, except scheduled reports).

### 17.2 In‑App Center
- Persistent bell icon with read/unread states.
- Deep‑links to relevant WO, ticket, or node.
- Notifications expire/archive after 30 days.

### 17.3 System Announcements (MVP)
- Managers can post broadcast announcements (e.g., “Plant shutdown on Sunday”) visible to all org users.

---

## 18. MOBILE / TABLET & QR ACCESS

- Fully responsive web UI.
- QR scan opens node data (history, manuals, profile, quick WO creation).
- **Mobile‑optimized quick actions**: “Complete WO”, “Add Counter Reading”, “Scan QR” – large touch targets.

---

## 19. FILES, STORAGE & MAINTENANCE TIMELINE

### 19.1 Attachments
- Allowed: JPEG, PNG, PDF, TXT, DOCX; max 10 MB; MIME validation.

### 19.2 Storage
- Server + S3‑compatible (MinIO) with org‑isolated buckets.

### 19.3 AI Vector Storage
- Extracted text from PDFs → embeddings in pgvector (org‑isolated).

### 19.4 Maintenance History / Timeline (MVP)
- Each node has a **chronological feed** showing all completed WOs, tickets, counter resets, part consumptions, and AI‑suggestion usage – with timestamps and user IDs.

---

## 20. SEARCH & NAVIGATION (MVP)

- **Global search bar** in header:
  - Search by node name, WO number, ticket ID, checklist/workflow name, and even **manual content** (RAG full‑text).
- **Filters** on all list pages (status, priority, date range, assignee).

---

## 21. COMMENTS & INTERNAL CHAT (MVP)

- Each WO and ticket has a **comment thread** where any assigned user can post messages, @mention others, and attach images.
- Comments are separate from the formal feedback loop and serve as collaborative history.

---

## 22. AI COPILOT – DETAILED SPECIFICATION (MVP)

### 22.1 AI Service Architecture
- Asynchronous tasks (Celery) call external LLM APIs (configurable endpoint/key).
- **Timeout & retry** with exponential backoff.
- **Fallback mode**: if external API fails, use a local lightweight model (e.g., sentence‑transformers for retrieval + rule‑based template) to provide a basic suggestion with a clear “fallback” flag.

### 22.2 AI‑Powered Features (all require human review)
- **Checklist generation** (from text prompt).
- **Workflow generation** (including parallel branches and conditional rules).
- **Troubleshooting/repair suggestions** (RAG + historical WO patterns).
- **Auto‑fill** of WO descriptions, parts lists, and estimated durations based on similar past WOs.

### 22.3 Confidence & Explainability
- Every AI suggestion shows a **confidence score** (0–100%) and a brief **rationale** (e.g., “based on 3 similar WOs for this node type” or “matched manual section 4.2”).
- Human may override, edit, or reject – each action is logged.

### 22.4 Data Collection for Continuous Learning (MVP)
- The system stores a **training dataset** with the following fields per interaction:
  - `org_id` (for isolation), `user_id`, `timestamp`.
  - `prompt` (original user input).
  - `ai_raw_output` (full LLM response).
  - `human_edited_version` (final approved content).
  - `approval_status` (approved / rejected / edited).
  - `confidence_score`, `fallback_used`.
- This dataset is **exportable** (JSONL/Parquet) by System Admin for offline fine‑tuning (LoRA/QLoRA) – ensuring the AI improves rapidly based on real usage.

### 22.5 Privacy & Multi‑Tenancy
- When sending prompts to external APIs, the system **strips organization_id and all PII** – only generic equipment types, measurement values, and anonymized text are sent.
- Alternatively, a local open‑source model can be configured for 100% data privacy.

---

## 23. BULK IMPORT / EXPORT (MVP)

- **Import** nodes, cycles, checklists, workflows, and parts via CSV/Excel (with validation and preview before commit).
- **Export** lists of WOs, tickets, nodes, and parts to CSV/PDF for offline analysis.

---

## 24. DATA SEEDING & ONBOARDING (MVP)

- **Pre‑built templates** when creating an organization:
  - “Facility Management” (HVAC, elevators, lighting).
  - “Fleet Maintenance” (vehicles, odometer‑based cycles).
  - “Manufacturing Line” (conveyors, motors, sensors).
- Each template includes sample zones, systems, cycles, checklists, and parts.
- A **guided wizard** for first‑time managers to adapt the template (rename, add/remove nodes) before going live.
- Interactive **tooltips** on key UI sections (Dashboard, WO list, AI Generator, Inventory).

---

## 25. ERROR HANDLING & USER FEEDBACK

- Clear, human‑readable validation messages (e.g., “Cannot delete – has 3 active WOs”).
- **Toast notifications** for background tasks (AI generation, import, report building) with a progress bar or status icon.
- A **task status center** where users can see pending async jobs and their results.

---

## 26. AUDIT LOGGING & UI

### 26.1 Immutable Audit Log (Database)
- Critical state changes: WO status, ticket escalations, safety flags, role changes, AI approval/rejection, inventory adjustments.
- Fields: Timestamp, User ID, Action, Entity ID, Previous State, New State, IP address.

### 26.2 Audit Log UI (MVP)
- Managers can view audit logs filtered by date, user, entity type, and action.
- Export audit log to CSV.

---

## 27. API, SECURITY & RATE LIMITING

- REST API with JWT (access + refresh tokens).
- RBAC enforced at API level (decorator/middleware).
- RLS in PostgreSQL for org/sub‑org isolation.
- Rate limiting: 100 req/min per IP/User (configurable).
- All endpoints require HTTPS in production.

---

## 28. DEPLOYMENT & OPERATIONAL REQUIREMENTS (MVP)

- **Environment configuration** via `.env` (separate for dev/staging/prod).
- **Database migrations** using Alembic – automated in CI/CD.
- **Docker Compose** for local development (Postgres, Redis, MinIO, Celery worker, Celery beat, web app).
- **Health check** endpoint (`/health`) returning DB, Redis, and AI service status.
- **Structured JSON logging** – all API requests and background tasks log to stdout for aggregation.
- **Sentry integration** (or similar) for error tracking – must be configurable.

---

## 29. POST‑MVP (EXPLICITLY DEFERRED)

- SSO/OAuth, MFA/2FA (already noted).
- Geolocation/maps (only optional zone geolocation field remains).
- Advanced inventory with purchase orders and supplier management.
- Mobile native apps (PWA is MVP).

---

## 30. SUMMARY OF MVP CHANGES VS ORIGINAL

| Feature                                         | Status in this document |
|-------------------------------------------------|-------------------------|
| Parallel workflows + conditional logic          | ✅ MVP                  |
| Inventory management (parts, usage, alerts)     | ✅ MVP                  |
| Seasonal cycles                                 | ✅ MVP                  |
| Sub‑organizations                               | ✅ MVP                  |
| AI fine‑tuning data collection                  | ✅ MVP                  |
| AI copilot (suggest + human review)             | ✅ MVP                  |
| Bulk import/export                              | ✅ MVP                  |
| Global search + filters                         | ✅ MVP                  |
| Comments on WO/tickets                          | ✅ MVP                  |
| Scheduled reports (email/PDF)                   | ✅ MVP                  |
| Maintenance timeline per node                   | ✅ MVP                  |
| System announcements                            | ✅ MVP                  |
| WO templates                                    | ✅ MVP                  |
| Mobile quick actions                            | ✅ MVP                  |
| Soft‑delete restoration                         | ✅ MVP                  |
| Audit log UI                                    | ✅ MVP                  |
| AI confidence score + fallback                  | ✅ MVP                  |
| Onboarding wizards & templates                  | ✅ MVP                  |
| Deployment essentials (Docker, Alembic, .env)   | ✅ MVP                  |

---
