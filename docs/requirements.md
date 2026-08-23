PROJECT REQUIREMENTS.TXT
OPEN-SOURCE CMMS WEB SAAS
CONSOLIDATED AND CLEANED REQUIREMENTS - MVP SCOPE (WITH AI PHASE 1 & 2)
================================================================================
1. PROJECT PURPOSE
================================================================================
The project is an open-source Computerized Maintenance Management System (CMMS)
delivered as a web-based SaaS.
The system shall allow organizations to manage:
- users and organizations,
- zones, systems, sub-systems, service points / nodes,
- maintenance and inspection cycles, workflows, checklists,
- work orders, repair tickets, attachments,
- basic reporting dashboards,
- AI-assisted checklist generation and manual retrieval (RAG).
The system shall be multi-tenant, with strict data isolation between
organizations.
================================================================================
2. CORE TECHNICAL STACK
================================================================================
Core backend language:
- Python.
Database:
- PostgreSQL (with pgvector extension for AI embeddings).
Architecture:
- Server API + web client.
Server API:
- REST architecture.
- JWT-based security.
Client:
- Node.js / React web client.
- The web client shall support bi-directional text entry.
- The system shall be accessible from mobile and tablet browsers.
AI & Async Processing:
- Celery (for background AI processing, cycle evaluation, and report generation).
- Redis (Celery broker, caching, delayed queues).
Target platform:
- Web SaaS.
- Mobile/tablet internet accessibility is required.
================================================================================
3. USER ACCOUNTS AND SIGNUP
================================================================================
3.1 User Signup
---------------
The system shall allow new users to sign up.
Signup requirements:
- Self-service registration.
- Email verification is required.
Post-MVP:
- SSO / OAuth.
- MFA / 2FA.
3.2 User Profile
----------------
Each user shall have a profile.
Profile shall include:
- Name, Email, Phone 1, Phone 2, Employee ID, Timezone.
3.3 Organization Membership
---------------------------
A user shall belong to only one organization at a time.
A user may change organization by accepting a new invitation.
3.4 User Deactivation
---------------------
Users can be deactivated.
Deactivated users:
- Shall not receive new task assignments.
- Shall not have their role changed.
- Historical records shall remain available.
3.5 System Administrator
------------------------
A system administrator role shall exist at platform level.
System administrator may:
- Override all limitations, delete users, change passwords.
- See all records for debugging.
- Perform platform-level administration.
3.6 Password Recovery
---------------------
The system shall support a "Forgot Password" flow.
- Users shall receive a secure, time-limited token (via email) to reset passwords.
- Passwords must meet minimum complexity requirements (e.g., min 8 chars, 1 uppercase, 1 number).
================================================================================
4. ORGANIZATION MANAGEMENT
================================================================================
4.1 Organization Creation
-------------------------
Users shall be able to create an organization. Each organization is a separate tenant.
4.2 Data Isolation
------------------
There shall be no data sharing between organizations at any rate.
4.3 Sub-Organizations
---------------------
Sub-organizations are a post-MVP feature.
4.4 Organization Profile
------------------------
Each organization shall have:
- Logo, Base contact information, 2 to 3 custom fields (Key-Value).
The base organization account shall also be treated as a zone for address/contact.
4.5 Zone Address and Contact
----------------------------
Each zone shall have: Address, Contact information.
4.6 Invitations
---------------
Invitation methods:
1. Email invitation with secure token for non-existing users.
2. Direct addition to organization for existing users (type-to-lookup).
Invitation expiry: Two weeks.
4.7 Subscription / Tier Limits
------------------------------
Tier limits apply to service points / nodes only:
- Free tier: up to 100 nodes.
- Pro tier: up to 1000 nodes.
- Ultimate tier: unlimited nodes.
No tier-based limit on structural entities (zones, systems).
4.8 Overdue Payment Behavior
----------------------------
Overdue organizations shall not be able to send repair tickets. All other features remain active.
================================================================================
5. ROLE MANAGEMENT
================================================================================
5.1 Organization Roles
----------------------
- Manager, Reporter, Operator, Maintenance.
5.2 Manager Role
----------------
Full setup rights (Zones, Systems, Nodes, Cycles, Schedules).
Can set cycles to launch automatically (1-2x per day/shift) or manually.
Full ticketing, review, and advanced reporting dashboard access.
5.3 Reporter Role
-----------------
Access advanced reporting dashboard.
Click existing manual cycles to advance them.
5.4 Operator Role
-----------------
Issue repair tickets, perform assigned operational inputs.
Log operating hours / operation counts. Execute assigned work where permitted.
5.5 Maintenance Role
--------------------
Receive repair tickets and work orders. Execute maintenance work.
Submit reports, submit feedback, reset counters where permitted.
================================================================================
6. ASSET HIERARCHY
================================================================================
6.1 General Hierarchy
---------------------
Organization -> Zone -> System -> Sub-system -> Service Point / Node.
Maximum total hierarchy depth: 6 levels.
6.2 Zones
---------
Multiple zones per organization. Flat or tree structure (max 2 breakdown levels).
Features: Status required, up to 5 custom fields, cloning required, address/contact required.
Status examples: Active, Inactive, Under construction, Decommissioned.
6.3 Zone Cloning
----------------
Cloning shall include: Full tree structure, profiles, cycles, workflows, checklists.
6.4 Geolocation
---------------
Post-MVP feature. Only zone may have a geolocation field in its profile page.
6.5 Systems
-----------
Each zone shall have systems/sub-systems. Systems may span between zones.
System depth: Maximum 2 levels (System -> Sub-system).
6.6 System Classification
-------------------------
Systems shall support taxonomy / classification.
6.7 Technical Specifications
----------------------------
Systems / equipment shall include general technical specifications.
Post-MVP: Different technical forms for each kind of equipment.
6.8 Prioritization
------------------
Assets and maintenance items shall support prioritization.
6.9 Barcode / QR Code
---------------------
Generate, print, read / scan.
6.10 Deletion and Cascade Rules
-------------------------------
- Hard deletion of structural entities is restricted.
- Deletion shall be a "Soft Delete" (Decommissioned/Archived status).
- If a parent is soft-deleted, all children inherit the status and become inaccessible for new Work Orders.
================================================================================
7. SERVICE POINTS / NODES / EQUIPMENT
================================================================================
7.1 Definition
--------------
Atomic maintenance unit. Independent, but may halt parent structure via safety flags.
7.2 Service Point Relationships
-------------------------------
Profile, maintenance history, manuals/documents, attachments, assigned cycles, spare parts placeholders.
7.3 Spare Parts / Parts Relationship
------------------------------------
1:N relationship to parts / spares. Inventory management is post-MVP.
Database design shall include connection slots for future inventory integration.
7.4 Counters
------------
Operation hours, operation count. Configurable by user. May inherit from parent.
7.5 Counter Reset
-----------------
Maintenance user can reset counters (node only, or optionally children). Does not affect unrelated parents.
7.6 Attachments
---------------
Photos, PDF files, Text files.
7.7 Decommissioning
-------------------
Supported. Decommissioned service points keep historical data available.
7.8 Node Lifecycle Status
-------------------------
Service points shall have a lifecycle status: Active, In Maintenance, Decommissioned.
Work orders and tickets can only be generated for Active nodes.
7.9 AI Manual Ingestion (RAG)
-----------------------------
PDF manuals attached to nodes shall be automatically parsed, chunked, and embedded into the vector database to enable the RAG Manual Assistant (See Section 25).
================================================================================
8. MAINTENANCE AND INSPECTION CYCLES
================================================================================
8.1 Assignment Scope
--------------------
Zone, System, Sub-system, Service point.
8.2 Cycle Trigger Types
-----------------------
Number of operations, hours of operation, natural / calendar hours.
8.3 Multiple Triggers
---------------------
First satisfied trigger wins and triggers the cycle.
8.4 Cron-Like Expressions
-------------------------
Supported for calendar-based cycles.
8.5 Manual Logging of Counters
------------------------------
Logged by Operator or Manager.
8.6 Grace Period / Deadline
---------------------------
After deadline: Flag critical stop or wait until completed.
8.7 Seasonal Cycles
-------------------
Post-MVP.
8.8 Postponement of Overhead Maintenance
----------------------------------------
Each cycle may be assigned to postpone overhead maintenance.
8.9 Missed Calendar Cycles
--------------------------
If a calendar-based cycle passes its deadline without triggering, the system shall generate an "Overdue" Work Order immediately upon the next system evaluation.
8.10 Cycle Suspension
---------------------
Managers can temporarily "Suspend" a cycle. Suspended cycles do not generate Work Orders, and calendar triggers pause until reactivated.
================================================================================
9. CYCLE INHERITANCE
================================================================================
9.1 Inheritance Direction
-------------------------
Top to bottom. Applies to operation hours/counts. Does not automatically apply to plans/schedules unless configured.
9.2 Influence Child Nodes
-------------------------
If flagged, child nodes cannot override the cycle.
9.3 Child Cycle Behavior
------------------------
Child cycles do not influence parents. Only safety flags can stop parents.
9.4 Effect of Parent Changes
----------------------------
Changes apply only to new instances. Existing instances are not retroactively changed.
================================================================================
10. WORKFLOWS AND CHECKLISTS
================================================================================
10.1 Assignment
---------------
Each cycle can be assigned a workflow or a checklist.
10.2 Unique Coding
------------------
Auto-generated, user-modifiable, must remain unique.
10.3 Searchability
------------------
Searchable per each item inside them. Each item stored separately.
10.4 Checklist Definition
-------------------------
Inspection only. Result type: Inspected, Pass, Fail.
10.5 Workflow Definition
------------------------
Instruction sets. Task states: Task, Started, Completed, Failed, Pending for task number, Performed by.
10.6 Workflow Constraints in MVP
--------------------------------
Post-MVP: Conditional triggers, parallel branches, versioning.
10.7 No Cross-Organization Sharing
----------------------------------
Workflows and checklists shall not be shared between organizations.
10.8 AI Automated Checklist Generation
--------------------------------------
Managers shall have access to an "AI Generate" button when creating checklists.
The system shall use a Text LLM to generate structured checklist items based on a text prompt (e.g., "Monthly maintenance for 500kVA Diesel Generator").
The AI shall output structured data including suggested activity descriptions, measurement units, and min/max thresholds.
================================================================================
11. WORK ITEMS / ACTIVITY ITEMS
================================================================================
Each item stored separately.
Core scheduling fields: Activity number, Planned/Assigned/Deadline/Started/Closed date/time.
Execution fields: Description, Status (Successful, Failed, Halted, Pending), Predecessor activity number.
Additional accepted V1 fields: Priority, Estimated/Actual duration, Assigned to, Required skills/certifications/tools/parts, Safety permit required, Risk level, Location override, Attachments, Digital signature, Notes/Comments, Cost, Downtime impact, Linked ticket ID, Completion percentage, Quality check by.
Measurement fields: Measurements, Measurement units, Min/Max thresholds.
Measurement Data Type: Measurements shall be typed as Numeric, Text, or Boolean (Pass/Fail).
Automatic pass/fail based on measurements is post-MVP.
================================================================================
12. WORK ORDERS
================================================================================
12.1 Work Order Creation
------------------------
Cycle triggers a work order (a copy of a workflow with date/execution info).
12.2 Work Order Identification
------------------------------
Work order number, unique reference.
12.3 Work Order Date Information
--------------------------------
Issue, Start, Finish, Stop date/time.
12.4 Work Order Acknowledgment
------------------------------
Automatic on user view.
12.5 Work Order Rejection
-------------------------
Requires description / reason.
12.6 Work Order Snooze
----------------------
Requires description. Allowed durations: 1h, 6h, 12h, 1d, 3d, 6d.
================================================================================
13. SAFETY / OPERATIONAL FLAGS
================================================================================
13.1 Cycle Flagging
-------------------
1. Hot inspect. 2. Pause for inspection. 3. Stop until task complete.
13.2 to 13.4 Definitions
------------------------
Hot inspect: Executed while running.
Pause: Continue running but stop shortly.
Stop: Stop operating until done.
13.5 Parent Structure Effect
----------------------------
Service point may halt parent structure. Only maintenance halts / safety flags can stop parents.
================================================================================
14. REPAIR TICKETING SYSTEM
================================================================================
14.1 Ticket Creation
--------------------
Operator and Manager can issue repair tickets. Sent to Maintenance.
14.2 Ticket Sections
--------------------
Report section, Feedback section.
14.3 Ticket Circulation Flow
----------------------------
1. Issue -> 2. Maintenance check/do -> 3. Maintenance reports -> 4. Issuer reviews -> 5. Accept/Feedback.
14.4 Feedback Loop Limit
------------------------
Report / feedback repeated up to 3 times.
14.5 Escalation After Failed Loops
----------------------------------
If unresolved after 3 loops, escalates to Manager. Manager decides to create new ticket or close.
14.6 Ticket Restrictions for Overdue Organizations
--------------------------------------------------
Overdue organizations cannot send repair tickets.
14.7 Ticket Priority & Severity
-------------------------------
Tickets shall require a priority level upon creation: Low, Medium, High, Critical.
14.8 Ticket Assignment Logic
----------------------------
Upon creation, tickets route to a "Maintenance Pool" (visible to all Maintenance users).
A Maintenance user can "Claim" a ticket, or a Manager can manually assign it to a specific user.
================================================================================
15. MAINTENANCE SCHEDULES AND LAUNCH MODES
================================================================================
15.1 Manager Setup
------------------
Manager creates all database setup and maintenance schedules.
15.2 Launch Modes
-----------------
Automatically (once or twice per day/shift) or Manually.
15.3 Reporter Manual Advancement
--------------------------------
Reporter can click existing manual cycles to advance them.
================================================================================
16. REPORTING AND DASHBOARDS
================================================================================
16.1 Dashboard Users
--------------------
Manager and Reporter access advanced reporting dashboard.
16.2 Dashboard Details
----------------------
Detailed reporting requirements developed later (must support filtering/export).
16.3 User Dashboard Counters
----------------------------
Each user sees number of New and Active work orders.
================================================================================
17. NOTIFICATIONS
================================================================================
17.1 Notification Channels
--------------------------
System notifications only. No email/SMS in MVP.
17.2 Persistent Login
---------------------
Mobile/tablet web client supports persistent login.
17.3 System Notifications
-------------------------
Examples: New work order, active update, ticket update, snooze expiration.
17.4 In-App Notification Center
-------------------------------
UI shall feature a persistent Notification Bell/Icon in the header.
Notifications have Read/Unread states.
Clicking deep-links to the relevant Work Order, Ticket, or Node.
Notifications expire/archive after 30 days.
================================================================================
18. MOBILE / TABLET AND QR CODE ACCESS
================================================================================
18.1 Mobile/Tablet Accessibility
--------------------------------
Accessible from mobile/tablet over internet.
18.2 QR Code Scanning
---------------------
Scanning node QR shows node data (history, manuals, profile).
18.3 QR / Barcode Capabilities
------------------------------
Generate, print, read / scan.
================================================================================
19. FILES AND STORAGE
================================================================================
19.1 Attachment Types
---------------------
Photos, PDF files, Text files.
19.2 Storage Location
---------------------
Server space + external storage connector (MinIO / S3-compatible).
19.3 Upload Constraints & Security
----------------------------------
Max file size: 10 MB (configurable).
System shall validate MIME types to block executables (.exe, .sh, .bat).
Allowed: Images (JPEG, PNG), Documents (PDF, TXT, DOCX).
19.4 AI Vector Storage
----------------------
Text extracted from PDFs for the RAG assistant shall be stored as vector embeddings in PostgreSQL (pgvector) or a dedicated vector index, strictly isolated by organization_id.
================================================================================
20. SECURITY AND ACCESS CONTROL
================================================================================
20.1 Authentication
-------------------
JWT-based.
20.2 API Architecture
---------------------
REST-based.
20.3 Organization Isolation
---------------------------
Strict isolation. No cross-organization access.
20.4 Role Enforcement
---------------------
RBAC enforced at API level.
20.5 Audit Logging
------------------
Immutable audit log for critical state changes (WO status, ticket escalations, safety flags, role changes).
Log includes: Timestamp, User ID, Action, Entity ID, Previous State, New State.
20.6 API Rate Limiting
----------------------
REST API shall implement rate limiting (e.g., 100 req/min per IP/User) to prevent abuse.
20.7 AI Data Privacy & Multi-tenancy
------------------------------------
When sending prompts to external LLM APIs, the system shall strip organization_id and PII.
Only generic equipment types and the specific text/image shall be sent.
Alternatively, local/open-source models may be used to guarantee 100% data privacy.
================================================================================
21. DATABASE DESIGN REQUIREMENTS
================================================================================
21.1 Primary Database
---------------------
PostgreSQL.
21.2 Multi-Tenant Design
------------------------
Strict organization-level isolation (Row-Level Security recommended).
21.3 Custom Fields
------------------
Organization (2-3), Zone (up to 5).
21.4 Hierarchy Support
----------------------
Zones, Systems, Sub-systems, Service points.
21.5 Future Inventory Slots
---------------------------
Parts table, spare parts table, service point parts relationship, work order part usage.
21.6 Vector Support
-------------------
Database shall support the pgvector extension to store text embeddings for the RAG Manual Assistant.
================================================================================
22. POST-MVP FEATURES
================================================================================
Explicitly postponed:
Authentication: SSO/OAuth, MFA/2FA.
Organization: Sub-organizations.
Geography: Geolocation/maps (limited to optional zone profile field).
Cycles: Seasonal cycles.
Workflows: Conditional triggers, parallel branches, versioning.
Inspection: Automatic pass
