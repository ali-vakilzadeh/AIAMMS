
# 📄 Master Project Specification: Open-Source CMMS SaaS

## 1. Project Overview
*   **Goal**: Build a scalable, open-source Computerized Maintenance Management System (CMMS) delivered as a web-based SaaS.
*   **Target Platforms**: Web browser (Desktop, Mobile, Tablet) with full internet accessibility. QR code scanning capability for field data access.
*   **Tech Stack**: 
    *   **Backend**: Python (REST API architecture)
    *   **Database**: PostgreSQL
    *   **Security**: JWT-based authentication and authorization
    *   **Frontend**: Node.js / React (Must support bi-directional text entry / RTL/LTR layouts)

## 2. User Management & Authentication
*   **Registration**: Self-service signup with mandatory email verification.
*   **Authentication**: Email/Password + JWT. (SSO/OAuth and MFA/2FA are deferred to Post-MVP).
*   **Organization Binding**: A user belongs to exactly **one** organization at a time. Users can change organizations by accepting a new invitation.
*   **User Profile Fields**: Name, Email, Phone 1, Phone 2, Employee ID, Timezone, Avatar.
*   **User States**: Active, Deactivated (Soft-delete: cannot be assigned new tasks, roles cannot be changed, historical data preserved).
*   **Super-Admin**: Platform-level administrator with override capabilities (delete users, reset passwords, view all records for debugging across all organizations).

## 3. Organization & Multi-Tenancy
*   **Data Isolation**: Strict multi-tenancy. Absolutely no data sharing between organizations.
*   **Subscription Tiers** (Node limits apply to "Service Points"):
    *   **Free**: Up to 100 nodes.
    *   **Pro**: Up to 1,000 nodes.
    *   **Ultimate**: Unlimited nodes.
*   **Overdue Payment State**: Organization retains access to all features *except* issuing new repair tickets.
*   **Organization Profile**: Logo, base contact info, 2–3 custom fields (Key-Value pairs). *Note: The base organization account also functions as a root "Zone".*
*   **Invitations**: 
    *   Existing users: Type-to-lookup email and add directly.
    *   New users: Email invitation with a secure token.
    *   Expiry: Invitations expire after 2 weeks.

## 4. Asset Hierarchy & Management
*   **Structure**: Tree-based hierarchy up to a maximum depth of 6 levels (e.g., Zone → Level A → Section B → System → Sub-system → Service Point/Node).
*   **Zones**: 
    *   Can be flat or nested (max 2-level breakdown under a zone).
    *   Profile includes: Address, Contact Info, Status (Active, Under Construction, Decommissioned), Geolocation (Post-MVP, profile only), up to 5 custom fields.
    *   **Cloning**: Full zone cloning supported (replicates tree structure, profiles, cycles, and workflows).
*   **Systems & Sub-Systems**: 
    *   Max 2 levels (System → Sub-system). 
    *   Can span across multiple zones.
    *   Requires Taxonomy/Classification tagging.
    *   General technical specifications (Manufacturer, Model, Serial, Install Date, Warranty). Specific equipment-type forms are Post-MVP.
*   **Service Points (Nodes)**:
    *   Atomic, independent units of maintenance.
    *   **QR/Barcode**: Auto-generate, print, and scan to view node profile, manuals, and maintenance history.
    *   **Attachments**: Photos, PDFs, Text files.
    *   **Decommissioning**: Supported while preserving full historical data.
    *   **Spare Parts**: 1:N relationship to a parts/spares catalog.

## 5. Maintenance & Inspection Engine
*   **Cycle Triggers**: 
    *   Natural time (Calendar/Cron-like expressions).
    *   Operating hours (Logged manually by Operator/Manager).
    *   Operation count (Logged manually, can inherit from parent).
    *   *Logic*: Multiple triggers allowed per cycle; the first to be met ("winner") triggers the work order. Repair personnel can manually reset counters.
*   **Inheritance Rules**:
    *   Operation hours/cycle counts can be inherited top-down.
    *   Parent cycles can be flagged to "influence child nodes" (mandatory inheritance; children cannot override).
    *   Child cycles do *not* influence parents.
    *   Edits to parent cycles apply only to *newly generated* work order instances.
*   **Safety & Operational Flags** (Inherited top-down, can halt parent structure):
    *   **Hot Inspect**: Task executed while node/parent is running.
    *   **Pause for Inspection**: Parent can run, but must shortly stop for the task.
    *   **Stop Until Task Complete**: Parent must stop operating until the task is done (e.g., wheel maintenance halts the car).
*   **Grace Period / Deadline**: Defined per cycle. If the deadline passes, the system enforces either "Flag Critical Stop" or "Wait Till Completed" based on configuration. (Seasonal cycles are Post-MVP).

## 6. Workflows, Checklists & Work Orders
*   **Definitions**:
    *   **Checklist**: Used for inspections only. Flat list of items with Pass/Fail outcomes.
    *   **Workflow**: Used for instruction sets. Sequential tasks with states (Started, Completed, Failed, Pending Predecessor Task #X, Performed By). No conditional or parallel branches in MVP.
*   **Identification**: Auto-generated unique code (modifiable by user, but system enforces uniqueness). No cross-organization sharing. (Versioning is Post-MVP).
*   **Work Order Generation**: A triggered cycle creates a Work Order, which is a dated instance/copy of the assigned Workflow/Checklist.
*   **Work Order Lifecycle**:
    *   **Acknowledgment**: Automatic upon user viewing the work order.
    *   **Actions**: User can Reject or Snooze the work order.
    *   **Snooze Durations**: 1 hour, 6 hours, 12 hours, 1 day, 3 days, 6 days (requires description).
*   **Comprehensive Work Item Fields (V1)**:
    *   Activity Number, Predecessor Activity Number
    *   Planned Date/Time, Assigned Date/Time, Deadline, Started Date/Time, Closed Date/Time
    *   Description, Status (Successful, Failed, Halted, Pending)
    *   Priority, Estimated Duration, Actual Duration
    *   Assigned To (User/Role), Required Skills/Certifications
    *   Required Tools, Required Parts (linked to inventory)
    *   Safety Permit Required (LOTO, Hot Work, etc.), Risk Level
    *   Location Override, Attachments (Photos/PDFs)
    *   Measurements/Readings (with manual pass/fail entry; no auto pass/fail in MVP)
    *   Digital Signature, Notes/Comments (threaded)
    *   Cost (Labor + Parts), Downtime Impact, Linked Ticket ID, Completion %, Quality Check By (Reviewer).

## 7. Ticketing System (Repair Requests)
*   **Initiation**: Operators and Managers can issue repair tickets.
*   **Routing**: Tickets are sent to the Maintenance role for action.
*   **5-Step Circulation Flow**:
    1. Ticket Issued (by Operator/Manager).
    2. Maintenance checks, performs work, and updates status.
    3. Maintenance submits Report/Feedback.
    4. Issuer reviews: Accepts to close the ticket OR sends feedback for corrections.
    5. **Loop Limit**: Steps 3 & 4 can repeat a maximum of **3 times**.
*   **Post-Limit Action**: After 3 feedback loops, the issuer *must* close the current ticket and issue a brand new one if the issue persists. (Escalation logic to be confirmed).

## 8. Roles & Permissions
*   **Manager**: Full setup rights (Zones, Systems, Nodes, Cycles, Schedules). Can set cycles to launch automatically (1-2x per day/shift) or manually. Full ticketing and dashboard access.
*   **Reporter**: Can view dashboards and manually advance/trigger existing manual cycles.
*   **Operator**: Can log operation hours/counts, execute assigned work orders, and issue repair tickets.
*   **Maintenance**: Receives tickets and work orders, executes tasks, updates statuses, and submits reports.

## 9. Reporting & Dashboards
*   **Users**: Manager and Reporter.
*   **Scope**: Advanced reporting dashboard (Specific KPIs and visualizations to be detailed in a subsequent phase, but must support export and filtering).

## 10. Technical & Non-Functional Requirements
*   **UI/UX**: Fully responsive for Mobile and Tablet internet access. Bi-directional text (RTL/LTR) support for inputs and layouts.
*   **Security**: JWT for API security, role-based access control (RBAC) enforced at the API level.
*   **Storage**: Secure storage for attachments (photos, PDFs). 
*   **Audit**: Implicit requirement for tracking state changes on critical safety flags and work order closures.
