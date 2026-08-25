Tribute to OpenSource Community

# Open-Source CMMS SaaS + AI Copilot + MCP Accessibility Project

## 📋 Project Status: **Active Development - Core Engine Complete**

**Development Progress: 10 of 12 roadmap chunks completed (83%)**

| Wave | Chunk | Module | Status | Description |
|------|-------|--------|--------|-------------|
| 0 | 1 | Core Kernel | ✅ Completed | Microkernel with module discovery, dependency graph, event bus, health supervision |
| 1 | 2 | Infrastructure | ✅ Completed | PostgreSQL (RLS), Redis cache, S3/MinIO storage, email services |
| 1 | 3 | API & Worker | ✅ Completed | FastAPI surface, Celery task engine with idempotency |
| 2 | 4 | Auth | ✅ Completed | JWT auth, RBAC, password flows, session management |
| 2 | 5 | Tenancy | ✅ Completed | Multi-tenancy, subscription tiers, quota enforcement, invitations |
| 3 | 6 | Assets | ✅ Completed | Asset hierarchy (zones/systems/service points), counters, QR codes, safety flags |
| 3 | 7 | Templates | ⏳ Pending | Workflow & checklist templates |
| 4 | 8 | Cycles | ✅ Completed | Maintenance cycle engine with calendar/hours/count triggers, evaluation logic |
| 4 | 9 | Work Orders | ✅ Completed | WO lifecycle: acknowledge/reject/snooze, execution, measurements, signatures |
| 5 | 10 | Tickets & Files | ✅ Completed | Repair ticketing with 5-step flow, file attachments with policy validation |
| 5 | 11 | AI Module | ✅ Completed | Checklist generation (LLM), RAG manual assistant with pgvector embeddings |
| 6 | 12 | MCP Server | ⏳ Pending | External AI agent interface for full system accessibility |

**Current Phase**: Core maintenance engine operational. Templates (Chunk 7) and MCP Server (Chunk 12) remain for completion.

---

## 🎯 Project Overview

An open-source **Computerized Maintenance Management System (CMMS)** delivered as a web-based SaaS platform with **AI-native integration** and **full AI agent accessibility via MCP**. Unlike conventional CMMS systems, this platform is designed from the ground up to be operated both by humans and AI agents equally.

### What Makes This Different from Conventional CMMS?

| Feature | Traditional CMMS | This Platform |
|---------|------------------|---------------|
| **AI Integration** | Bolt-on analytics or chatbot | Native AI copilot embedded in core workflow (checklist generation, RAG manual assistant) |
| **Accessibility** | Human-only UI/API | Full MCP (Model Context Protocol) support - external AI agents can operate the entire system |
| **Architecture** | Monolithic or tightly-coupled modules | Microkernel design with isolated, health-monitored modules that can be independently developed and tested |
| **Multi-Tenancy** | Shared database with application-level filtering | PostgreSQL Row-Level Security (RLS) enforced at database level for strict data isolation |
| **Maintenance Triggers** | Simple calendar or meter readings | Multi-trigger cycles (calendar/cron, operating hours, operation counts) with inheritance propagation and "first satisfied wins" logic |
| **Safety Integration** | Separate safety systems or manual flags | Built-in safety flags (HOT_INSPECT, PAUSE_FOR_INSPECTION, STOP_UNTIL_COMPLETE) that propagate through hierarchy and halt parent operations |
| **Ticket Resolution** | Open-ended feedback loops | Enforced 5-step circulation with maximum 3 feedback loops, auto-escalation to prevent infinite rework |
| **Counter Inheritance** | Manual entry per asset | Top-down counter inheritance with influence propagation - log once at parent, children inherit automatically |
| **QR Code Access** | Static labels linking to fixed URLs | Dynamic QR resolution showing role-filtered views (manuals, work orders, tickets, history) based on who scans |
| **Zone Cloning** | Manual recreation or export/import | One-click zone cloning with background worker replication preserving structure, custom fields, and generating unique IDs |
| **Data Privacy (AI)** | Send all data to LLM provider | PII and organization ID stripped before any external LLM call, vector embeddings stored locally in pgvector |

### Target Platforms
- Web browser (Desktop, Mobile, Tablet)
- Full internet accessibility
- QR code scanning capability for field data access
- **External AI agents via MCP protocol**

---

## 🏗️ Tech Stack

| Component | Technology |
|-----------|------------|
| **Backend** | Python (REST API architecture) |
| **Database** | PostgreSQL (with pgvector extension for AI embeddings) |
| **Frontend** | Node.js / React |
| **Authentication** | JWT-based authentication and authorization |
| **Async Processing** | Celery (background AI processing, cycle evaluation, report generation) |
| **Caching/Queues** | Redis (Celery broker, caching, delayed queues) |
| **Storage** | MinIO / S3-compatible external storage |

### Key Technical Requirements
- Bi-directional text entry support (RTL/LTR layouts)
- Mobile and tablet browser accessibility
- Role-based access control (RBAC) enforced at API level
- Strict multi-tenancy with organization-level data isolation

---

## 🚀 Core Features (MVP Scope)

### 1. User Management & Authentication
- Self-service registration with email verification
- Email/Password + JWT authentication
- Single organization membership per user
- User profile: Name, Email, Phone, Employee ID, Timezone, Avatar
- User states: Active, Deactivated (soft-delete)
- Super-Admin role for platform-level administration
- Password recovery with secure time-limited tokens

### 2. Organization & Multi-Tenancy
- Strict data isolation between organizations
- **Subscription Tiers** (based on Service Point/Node limits):
  - **Free**: Up to 100 nodes
  - **Pro**: Up to 1,000 nodes
  - **Ultimate**: Unlimited nodes
- Organization profile: Logo, contact info, custom fields
- Invitation system (email token for new users, direct add for existing)
- Invitations expire after 2 weeks
- Overdue payment state: Access retained except for issuing new repair tickets

### 3. Asset Hierarchy & Management
- **Tree-based hierarchy** (max 6 levels):
  ```
  Organization → Zone → Level A → Section B → System → Sub-system → Service Point/Node
  ```
- **Zones**: Flat or nested (max 2-level breakdown), status tracking, cloning support
- **Systems & Sub-Systems**: Max 2 levels, taxonomy/classification tagging
- **Service Points (Nodes)**:
  - Atomic maintenance units
  - QR/Barcode auto-generation, print, and scan
  - Attachments: Photos, PDFs, Text files
  - Decommissioning with historical data preservation
  - 1:N relationship to spare parts catalog

### 4. Maintenance & Inspection Engine
- **Cycle Triggers**:
  - Natural time (Calendar/Cron-like expressions)
  - Operating hours (manual logging)
  - Operation count (manual logging, can inherit from parent)
  - First satisfied trigger wins
- **Inheritance Rules**:
  - Top-down inheritance for operation hours/counts
  - Parent cycles can mandate child inheritance
  - Edits apply only to newly generated work orders
- **Safety & Operational Flags**:
  - Hot Inspect (task while running)
  - Pause for Inspection (stop shortly)
  - Stop Until Task Complete (halt parent)
- Grace period/deadline enforcement with configurable actions

### 5. Workflows, Checklists & Work Orders
- **Checklist**: Inspection-focused, Pass/Fail outcomes
- **Workflow**: Sequential instruction sets with task states
- Auto-generated unique codes (user-modifiable, system-enforced uniqueness)
- **Work Order Lifecycle**:
  - Automatic acknowledgment on view
  - Reject or Snooze actions
  - Snooze durations: 1h, 6h, 12h, 1d, 3d, 6d
- **Comprehensive Work Item Fields**: Activity numbers, dates, status, priority, assignments, tools, parts, safety permits, measurements, digital signatures, costs, quality checks

### 6. Ticketing System (Repair Requests)
- **Initiation**: Operators and Managers can issue tickets
- **5-Step Circulation Flow**:
  1. Ticket Issued
  2. Maintenance performs work and updates status
  3. Maintenance submits Report/Feedback
  4. Issuer reviews: Accept to close OR send feedback
  5. Loop limit: Steps 3 & 4 repeat max **3 times**
- Post-limit: Issuer must close and create new ticket if issue persists
- Ticket priority levels: Low, Medium, High, Critical
- Assignment via Maintenance Pool or Manager assignment

### 7. Roles & Permissions
| Role | Capabilities |
|------|-------------|
| **Manager** | Full setup rights, cycle configuration, ticketing, dashboards |
| **Reporter** | View dashboards, manually advance manual cycles |
| **Operator** | Log hours/counts, execute work orders, issue tickets |
| **Maintenance** | Receive tickets/WOs, execute tasks, submit reports, reset counters |

### 8. Reporting & Dashboards
- Access: Manager and Reporter roles
- Advanced reporting dashboard with filtering and export support
- User dashboard counters: New and Active work orders

### 9. Notifications
- In-app notification center (Notification Bell/Icon)
- Read/Unread states
- Deep-linking to relevant entities
- 30-day expiration/archive
- Examples: New work order, ticket update, snooze expiration

### 10. AI Features (Phase 1 & 2)
- **AI Checklist Generation**: Text LLM generates structured checklists from prompts
- **RAG Manual Assistant**: PDF manuals parsed, chunked, embedded for retrieval
- Vector storage in PostgreSQL (pgvector)
- Data privacy: PII stripped before external LLM calls

---

## 🔒 Security & Compliance

- JWT-based API security
- Row-Level Security (RLS) recommended for multi-tenancy
- RBAC enforced at API level
- Immutable audit logging for critical state changes
- API rate limiting (e.g., 100 req/min per IP/User)
- File upload validation (MIME type checking, 10 MB default limit)
- AI data privacy: Organization ID and PII stripped before external API calls

---

## 📁 File & Storage

- Supported attachment types: Images (JPEG, PNG), Documents (PDF, TXT, DOCX)
- Blocked: Executables (.exe, .sh, .bat)
- Storage: Server space + external connector (MinIO/S3)
- AI vector embeddings stored in PostgreSQL (pgvector)

---

## 📅 Post-MVP Features

The following features are explicitly postponed to future phases:

- **Authentication**: SSO/OAuth, MFA/2FA
- **Organization**: Sub-organizations, geolocation (profile only)
- **Cycles**: Seasonal cycles
- **Equipment**: Type-specific technical forms
- **Workflows**: Conditional triggers, parallel branches, versioning
- **Measurements**: Automatic pass/fail based on thresholds
- **Inventory**: Full parts/spares inventory management
- **Notifications**: Email/SMS notifications
- **Ticketing**: Escalation logic refinement

---

## 📐 Database Design Highlights

- **Primary Database**: PostgreSQL with pgvector extension
- **Multi-Tenant Design**: Strict organization-level isolation
- **Custom Fields**: Organization (2-3), Zone (up to 5)
- **Hierarchy Support**: Zones, Systems, Sub-systems, Service Points
- **Future Inventory Slots**: Parts tables, spare parts relationships, WO part usage

---

## 🛠️ Development Guidelines

### API Architecture
- REST-based design
- JWT authentication required for all protected endpoints
- Rate limiting implemented per IP/User

### Frontend Requirements
- Responsive design for mobile/tablet
- Bi-directional text (RTL/LTR) support for inputs and layouts
- Persistent login support for mobile devices
- QR code scanning integration

### Audit Logging
All critical state changes must be logged immutably:
- Work Order status changes
- Ticket escalations
- Safety flag modifications
- Role changes
- Log includes: Timestamp, User ID, Action, Entity ID, Previous State, New State

---

## 📞 Support & Administration

### System Administrator
Platform-level administrator with capabilities to:
- Override all limitations
- Delete users, reset passwords
- View all records across all organizations for debugging

### Password Recovery
- Secure, time-limited token via email
- Minimum complexity: 8 characters, 1 uppercase, 1 number


