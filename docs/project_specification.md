# MASTER PROJECT SPECIFICATION  
## AIAMMS – AI‑Assisted Maintenance Management System  
### Open‑Source CMMS SaaS (MVP Scope)

---

## 1. PROJECT OVERVIEW

**Goal**  
Build a scalable, open‑source Computerized Maintenance Management System (CMMS) delivered as a web‑based SaaS. The system acts as an **AI copilot** – it accelerates data entry, generates checklists/workflows, and suggests repair steps, but **all AI outputs require human review and approval** before they affect live operations. The system continuously collects interaction data to enable rapid model improvement through fine‑tuning.

**Target Platforms**  
- Web browsers (Desktop, Mobile, Tablet) with full internet accessibility.  
- QR/barcode scanning for instant field access to node profiles, manuals, and history.

**Core Tech Stack**  
| Layer               | Technology                                                       |
|---------------------|------------------------------------------------------------------|
| Backend             | Python 3.11+ (REST API)                                          |
| API Framework       | FastAPI or Django                                                |
| Database            | PostgreSQL 15+ with **pgvector** extension                       |
| Security            | JWT‑based authentication + RBAC                                  |
| Async Processing    | Celery + Redis (broker & cache)                                  |
| Frontend            | React 18+ / Node.js – supports RTL/LTR bi‑directional text      |
| File Storage        | Server disk + S3‑compatible (MinIO)                              |
| AI Integration      | External LLM API (configurable) + local fallback model           |
| AI Training Pipeline| Data collection service + export scripts for fine‑tuning (LoRA)  |
| Deployment          | Docker Compose (dev) + Kubernetes‑ready (prod), Alembic for migrations |

---

## 2. USER MANAGEMENT & AUTHENTICATION

### 2.1 Registration & Authentication
- **Self‑service signup** with email verification (time‑limited token).  
- **Login**: Email/Password + JWT (access + refresh tokens).  
- **Password policy**: min 8 chars, 1 uppercase, 1 number.  
- **Forgot password** flow with secure, time‑limited reset token.  
- SSO/OAuth and MFA/2FA are **post‑MVP**.

### 2.2 User Profile
- Fields: **Name, Email, Phone 1, Phone 2, Employee ID, Timezone, Avatar** (optional).  
- Profile is editable by the user (except email – requires verification for change).

### 2.3 Organization Binding & Sub‑Organizations
- A user belongs to **exactly one primary organization** at a time.  
- Users can switch organizations by accepting a new invitation.  
- **Sub‑organizations** (nested tenants) are **MVP**:  
  - Parent org can create child orgs with separate data isolation.  
  - Users can be shared across parent/child via invitations with inherited roles.  
  - Sub‑orgs have their own tier limits (see 3.3) but can be centrally managed by parent admins.

### 2.4 User States
- **Active** – full access per role.  
- **Deactivated** (soft‑delete):  
  - Cannot be assigned new tasks.  
  - Role cannot be changed.  
  - Historical records (WOs, tickets, comments) remain intact.

### 2.5 System Administrator (Platform Level)
- Platform‑level super‑admin with override capabilities:  
  - Delete any user, reset any password.  
  - View all records across all organizations (debug mode).  
  - Manage platform‑wide AI model settings and export fine‑tuning datasets.

---

## 3. ORGANIZATION & MULTI‑TENANCY (WITH SUB‑ORGS)

### 3.1 Data Isolation
- **Strict multi‑tenancy** – absolutely no data sharing between organizations or sub‑orgs.  
- Enforced via **Row‑Level Security (RLS)** in PostgreSQL and application‑level RBAC.

### 3.2 Organization Profile
- Logo, base contact info, 2–3 custom Key‑Value fields.  
- The base organization account also functions as a root **“Zone”** for address/contact purposes.

### 3.3 Subscription Tiers (Node limits apply to Service Points)
| Tier      | Max Nodes | Sub‑orgs allowed |
|-----------|-----------|------------------|
| Free      | 100       | 0                |
| Pro       | 1,000     | up to 5          |
| Ultimate  | Unlimited | unlimited        |

### 3.4 Overdue Payment State
- Organization retains access to **all features** except issuing new repair tickets.

### 3.5 Invitations
- **Existing users**: Type‑to‑lookup by email and add directly.  
- **New users**: Email invitation with secure token (expires after 2 weeks).  
- Invitations can be scoped to a specific sub‑organization.

---

## 4. ASSET HIERARCHY & MANAGEMENT (INCLUDING SUB‑ORGS)

### 4.1 Hierarchy Structure
- Tree‑based with maximum depth of **6 levels**:  
  `Org → Sub‑Org → Zone → Level A (optional) → System → Sub‑system → Service Point/Node`.

### 4.2 Zones
- Can be flat or nested (max 2‑level breakdown under a zone).  
- **Profile includes**: Address, Contact Info, Status (Active, Under Construction, Decommissioned), up to 5 custom fields.  
- **Geolocation** (post‑MVP; only an optional text/coordinate field in profile).  
- **Cloning**: Full zone cloning – replicates entire tree, profiles, cycles, workflows, and inventory links.

### 4.3 Systems & Sub‑Systems
- Max 2 levels (`System → Sub‑system`).  
- Systems may **span across multiple zones**.  
- **Taxonomy/Classification** tagging is required.  
- **Technical specifications**: Manufacturer, Model, Serial, Install Date, Warranty – generic fields (equipment‑specific forms are post‑MVP).

### 4.4 Service Points (Nodes)
- **Atomic maintenance units** – independent, but may halt parent structure via safety flags.  
- **QR/Barcode**: Auto‑generate, print, and scan to view node profile, manuals, attachments, and maintenance history.  
- **Lifecycle Status**: Active, In Maintenance, Decommissioned.  
  - Work orders and tickets can be generated **only for Active** nodes.  
- **Attachments**: Photos, PDFs, TXT, DOCX (max 10 MB, MIME validation).  
- **Decommissioning**: Fully supported – all historical data preserved.  
- **Soft‑delete restoration**: Managers can restore a soft‑deleted zone/system/node within 30 days (restoration resets status to Active).

### 4.5 Spare Parts & Inventory (MVP)
- **Parts catalog**: Name, SKU, Manufacturer, Min/Max stock, Unit cost, Supplier info.  
- **Node‑Parts relationship**: 1:N – which parts are used on which node.  
- **Work Order‑Parts consumption**: Track quantities used per WO, auto‑decrement stock, raise low‑stock alerts (configurable thresholds).  
- Inventory management is **fully MVP** – no deferral.

---

## 5. MAINTENANCE & INSPECTION ENGINE

### 5.1 Cycle Triggers (Multiple allowed per cycle)
- **Natural time** – Cron‑like expressions (calendar).  
- **Operating hours** – logged manually by Operator/Manager (can inherit from parent).  
- **Operation count** – logged manually (can inherit).  
- **Seasonal cycles** (MVP) – e.g., “every winter solstice” or quarterly based on meteorological seasons with date ranges.  
- **Logic**: First trigger satisfied (“winner”) generates the Work Order.

### 5.2 Counter Management
- Operators and Managers log counter readings manually.  
- Maintenance users can **reset counters** (node only, or recursively to children).  
- Counters may be inherited top‑down (hours/counts).

### 5.3 Inheritance Rules
- **Top‑down** inheritance (Org → Sub‑Org → Zone → …).  
- Parent cycles can be flagged to **“influence children”** – mandatory inheritance; children cannot override.  
- Child cycles **do not influence parents** (except safety flags).  
- Changes to parent cycles apply **only to newly generated** Work Order instances – existing WOs are not retroactively altered.

### 5.4 Safety & Operational Flags (inherited top‑down, can halt parent structure)
| Flag               | Effect                                                                 |
|--------------------|------------------------------------------------------------------------|
| **Hot Inspect**    | Task executed while node/parent is running.                            |
| **Pause for Inspection** | Parent can run, but must stop shortly for the task.                  |
| **Stop Until Task Complete** | Parent must stop operating until the task is finished.            |

### 5.5 Grace Period / Deadline
- Defined per cycle.  
- After deadline passes, the system either **flags a Critical Stop** or **waits until completed** (manager’s choice).  
- **Missed calendar cycles**: The next system evaluation creates an “Overdue” Work Order immediately.

### 5.6 Cycle Suspension
- Managers can temporarily **suspend** a cycle – no WO generation, calendar triggers pause until reactivated.

---

## 6. WORKFLOWS, CHECKLISTS & WORK ORDERS (MVP EXTENDED)

### 6.1 Checklist
- Used for inspections only.  
- Flat list of items, each with result: **Inspected, Pass, Fail**.

### 6.2 Workflow (MVP with parallel & conditional logic)
- **Instruction sets** with tasks.  
- **Task states**: Task, Started, Completed, Failed, Pending (with predecessor reference), Performed By.  
- **Parallel branches**: Tasks can run concurrently (AND splits/joins).  
- **Conditional logic**: If‑then‑else branches based on measurement values or previous task outcomes (e.g., “If temperature > 80 °C, run cooling check”).  
- **Versioning**: Workflows are versioned – each WO references the specific version used at creation.

### 6.3 Identification
- Auto‑generated unique code (user‑modifiable, but system enforces uniqueness per org).  
- No cross‑org sharing of workflows/checklists.

### 6.4 Work Order Generation
- A triggered cycle creates a Work Order – a dated **instance/copy** of the assigned Workflow/Checklist version.

### 6.5 Work Order Lifecycle
- **Acknowledgment**: Automatic upon user viewing the WO.  
- **Rejection**: Requires description/reason.  
- **Snooze**: Allowed durations – 1 h, 6 h, 12 h, 1 d, 3 d, 6 d – with mandatory reason.  
- **Completion**: All tasks must be completed; WO status reflects the overall outcome.

### 6.6 Work Item Fields (V1 – all mandatory)
| Field Group               | Specific Fields                                                                 |
|---------------------------|---------------------------------------------------------------------------------|
| Identification            | Activity Number, Predecessor Activity Number                                    |
| Scheduling                | Planned, Assigned, Deadline, Started, Closed (date/time)                        |
| Execution                 | Description, Status (Successful/Failed/Halted/Pending), Priority                |
| Assignment                | Assigned To (User/Role), Required Skills/Certifications                         |
| Resources                 | Required Tools, Required Parts (linked to inventory)                            |
| Safety                    | Safety Permit Required (LOTO, Hot Work, etc.), Risk Level                       |
| Location & Attachments    | Location Override, Attachments (Photos/PDFs)                                    |
| Measurements              | Numeric, Text, or Boolean (Pass/Fail) with min/max thresholds – **auto pass/fail is MVP** (system compares values). |
| Collaboration             | Digital Signature, Notes/Comments (threaded)                                    |
| Financial & Impact        | Cost (Labor + Parts), Downtime Impact, Linked Ticket ID                         |
| Progress                  | Completion %, Quality Check By (Reviewer)                                       |

### 6.7 Work Order Templates (MVP)
- After completing a WO, a Manager can **“Save as Template”** – clones the workflow, checklist, and assigned parts into a reusable template for future cycles.

---

## 7. TICKETING SYSTEM (REPAIR REQUESTS)

### 7.1 Initiation & Priority
- Operators and Managers can issue repair tickets.  
- **Priority** (Low, Medium, High, Critical) is required on creation.

### 7.2 Routing & Assignment
- Tickets route to a **“Maintenance Pool”** (visible to all Maintenance users).  
- A Maintenance user can **Claim** a ticket, or a Manager can assign it directly.

### 7.3 5‑Step Circulation Flow (with loop limit)
1. **Ticket Issued** (by Operator/Manager).  
2. **Maintenance** checks, performs work, updates status.  
3. **Maintenance submits Report/Feedback**.  
4. **Issuer reviews**: Accepts to close OR sends feedback for corrections.  
5. **Loop limit**: Steps 3–4 can repeat **maximum 3 times**.  
   - After 3 loops, the issuer **must** close the current ticket and create a new one if unresolved.

### 7.4 Ticket Restrictions
- Overdue organizations **cannot send new repair tickets** (all other features remain active).

### 7.5 AI Troubleshooting Copilot (MVP)
- When a ticket is opened, the system automatically **suggests probable causes and repair steps** (RAG over node manuals + historical WO patterns).  
- Maintenance user **reviews the suggestions**, can edit them, and **approves** the final action plan before executing.  
- All suggestions and edits are logged for AI fine‑tuning.

---

## 8. ROLES & PERMISSIONS (Org & Sub‑Org Level)

| Role       | Permissions                                                                                                                                 |
|------------|---------------------------------------------------------------------------------------------------------------------------------------------|
| **Manager**| Full setup rights (Zones, Systems, Nodes, Cycles, Workflows, Inventory).<br>Set auto/manual launch modes (1–2× per day/shift).<br>Full ticketing & advanced dashboard access.<br>**Approve AI‑generated checklists/workflows before they go live.**<br>View/edit AI training logs for their org. |
| **Reporter**| Advanced dashboard access, scheduled reports, manually advance existing cycles.<br>Can **suggest edits** to AI outputs (but not approve).    |
| **Operator**| Log operation hours/counts, execute assigned WOs, issue repair tickets.<br>Receive AI‑assisted troubleshooting suggestions on tickets.        |
| **Maintenance**| Receive tickets/WOs, execute work, update statuses, submit reports, reset counters.<br>Review AI‑generated repair steps, edit/confirm before closing. |

---

## 9. REPORTING & DASHBOARDS

### 9.1 Access
- Manager and Reporter.

### 9.2 Core Dashboards (MVP)
- **Live counters**: New/Active WOs, overdue tickets, low‑stock alerts.  
- **Filtering** by date, node, status, priority, assignee – and **export** to CSV/PDF.  
- **Maintenance history timeline** per node (see 12.4).

### 9.3 Scheduled Reports (MVP)
- Managers can schedule **weekly/monthly summary reports** (PDF) – delivered to their email or downloadable from the notification center.

---

## 10. AI COPILOT – DETAILED SPECIFICATION (MVP)

### 10.1 AI Service Architecture
- Asynchronous Celery tasks call external LLM APIs (configurable endpoint/key).  
- **Timeout & retry** with exponential backoff.  
- **Fallback mode**: If external API fails, use a local lightweight model (sentence‑transformers for retrieval + rule‑based templates) – clearly flagged as “fallback”.

### 10.2 AI‑Powered Features (all require human review)
- **Checklist generation** from a text prompt (e.g., “Monthly maintenance for 500kVA Diesel Generator”).  
- **Workflow generation** – including parallel branches and conditional rules.  
- **Troubleshooting/repair suggestions** – RAG over manuals + historical WO data.  
- **Auto‑fill** of WO descriptions, parts lists, and estimated durations based on similar past WOs.

### 10.3 Confidence & Explainability
- Every AI suggestion shows a **confidence score** (0–100%) and a brief **rationale** (e.g., “based on 3 similar WOs for this node type” or “matched manual section 4.2”).  
- Human may **edit or reject** – each action is logged.

### 10.4 Data Collection for Continuous Learning (MVP)
- The system stores a **training dataset** per interaction:  
  - `org_id`, `sub_org_id`, `user_id`, `timestamp`.  
  - `prompt` (original input).  
  - `ai_raw_output` (full LLM response).  
  - `human_edited_version` (final approved content).  
  - `approval_status` (approved / rejected / edited).  
  - `confidence_score`, `fallback_used`.  
- This dataset is **exportable** (JSONL/Parquet) by System Admin for offline fine‑tuning (LoRA/QLoRA) – enabling rapid, continuous improvement.

### 10.5 Privacy & Multi‑Tenancy
- When sending prompts to external APIs, the system **strips all PII and organization identifiers** – only generic equipment types, measurement values, and anonymised text are transmitted.  
- Local open‑source models can be configured for 100% data privacy.

---

## 11. BULK IMPORT / EXPORT (MVP)

- **Import** nodes, cycles, checklists, workflows, and parts via CSV/Excel – with validation and preview before commit.  
- **Export** lists of WOs, tickets, nodes, parts, and audit logs to CSV/PDF.

---

## 12. ADDITIONAL ESSENTIAL FEATURES (MVP)

### 12.1 Onboarding & Data Seeding
- **Pre‑built templates** when creating an organization:  
  - “Facility Management” (HVAC, elevators, lighting).  
  - “Fleet Maintenance” (odometer‑based cycles).  
  - “Manufacturing Line” (conveyors, motors, sensors).  
- Each template includes sample zones, systems, cycles, checklists, and parts.  
- **Guided wizard** for first‑time managers to adapt the template (rename, add/remove) before going live.  
- Interactive **tooltips** on key UI sections (Dashboard, WO list, AI Generator, Inventory).

### 12.2 Global Search & Navigation
- **Global search bar** in header – searches node names, WO numbers, ticket IDs, checklist/workflow names, and even **manual content** (RAG full‑text).  
- **Filters** on all list pages (status, priority, date range, assignee).

### 12.3 Comments & Internal Chat
- Each WO and ticket has a **threaded comment section** – any assigned user can post, @mention others, and attach images.  
- Comments are separate from the formal feedback loop and serve as collaborative history.

### 12.4 Maintenance History / Timeline per Node
- A **chronological feed** showing all completed WOs, tickets, counter resets, part consumptions, and AI‑suggestion usage – with timestamps and user IDs.

### 12.5 System Announcements
- Managers can post broadcast announcements (e.g., “Plant shutdown on Sunday”) visible to all users of that org/sub‑org.

### 12.6 Mobile Quick Actions
- Optimised touch targets: “Complete WO”, “Add Counter Reading”, “Scan QR” – for field use.

---

## 13. TECHNICAL & NON‑FUNCTIONAL REQUIREMENTS

### 13.1 UI/UX
- Fully responsive for Mobile and Tablet internet access.  
- Bi‑directional text (RTL/LTR) support for inputs and layouts.

### 13.2 Security & Rate Limiting
- JWT‑based API security with refresh tokens.  
- RBAC enforced at **API level** (decorator/middleware).  
- RLS in PostgreSQL for org/sub‑org isolation.  
- Rate limiting: 100 req/min per IP/User (configurable).  
- All endpoints require HTTPS in production.

### 13.3 Storage
- Secure storage for attachments (photos, PDFs, DOCX) – server disk + S3‑compatible (MinIO) with org‑isolated buckets.  
- AI vector embeddings stored in **pgvector** – strictly isolated by `org_id` and `sub_org_id`.

### 13.4 Audit Logging
- Immutable audit log for all critical state changes:  
  - WO status, ticket escalations, safety flags, role changes, AI approval/rejection, inventory adjustments.  
- Fields: Timestamp, User ID, IP address, Action, Entity ID, Previous State, New State.  
- **Audit Log UI** (MVP): Managers can view and filter logs (by date, user, entity, action) and export to CSV.

### 13.5 Deployment & DevOps
- **Environment‑based configuration** (`.env` for dev/staging/prod).  
- **Database migrations** via Alembic – automated in CI/CD.  
- **Docker Compose** for local development (Postgres, Redis, MinIO, Celery worker, Celery beat, web app).  
- **Health check** endpoint (`/health`) returning DB, Redis, and AI service status.  
- **Structured JSON logging** – all API requests and background tasks log to stdout for aggregation.  
- **Sentry integration** (or similar) for error tracking – configurable.

---

## 14. POST‑MVP (EXPLICITLY DEFERRED)

- SSO/OAuth, MFA/2FA.  
- Advanced geolocation/maps (only the optional zone geo field remains).  
- Equipment‑specific technical forms.  
- Advanced inventory with purchase orders and supplier portals.  
- Native mobile apps (PWA is MVP).  
- Additional AI capabilities (e.g., image recognition) – not in scope for MVP.

