Based on your excellent feedback, the UI paradigm shifts from a traditional multi-page website to a **persistent workspace application** (similar to an IDE or advanced browser). 

Here is the revised and comprehensive UI element report, incorporating the global layout, the tabbed workspace, the persistent asset tree, the global AI side-band, and your specific page-level requirements.

### 0. Global Screen Layout (Persistent Across All Tabs)
0.1. **Top Header Bar** (story: persistent bar containing logo, global search, RTL/LTR layout toggle, notification bell with unread badge, and user profile dropdown)
0.2. **View-Tab Bar** (story: Firefox-style tab strip located below the header; users can open multiple pages as tabs, close them, or pin them. Only the active tab's content is rendered in the main workspace)
0.3. **Left Asset Tree Band** (story: collapsible hierarchical sidebar showing Organization → Zones → Systems → Sub-systems → Nodes. Clicking any item opens or focuses its corresponding detail tab in the workspace. Replaces standalone "list" pages for assets)
0.4. **Right AI Side-band** (story: collapsible panel on the right edge of the screen, accessible from *any* active tab. Contains the AI Manual Assistant (RAG) and contextual AI tools. Can be expanded to half-screen or collapsed to a thin icon strip)
0.5. **Main Workspace** (story: the central area rendering the content of the currently active View-Tab)

---

### 1. List of Pages (Available as View-Tabs)
1.1. Login Page
1.2. Signup Page
1.3. Email Verification Page
1.4. Forgot Password Page
1.5. Reset Password Page
1.6. Main Dashboard
1.7. Zones Management (List & Creation)
1.8. Zone Detail & Cloning *(Maps to your Page 9)*
1.9. Systems & Sub-Systems Detail *(Maps to your Page 10)*
1.10. Service Points / Nodes Detail *(Maps to your Page 11)*
1.11. QR Code Scanner (Mobile View)
1.12. Work Orders List
1.13. Work Order Execution
1.14. Workflows & Checklists *(Maps to your Page 14)*
1.15. Cycles Management *(Maps to your Page 15)*
1.16. Checklist/Workflow Editor (with AI)
1.17. Repair Tickets List
1.18. Ticket Detail & Feedback Flow
1.19. Reports & KPIs
1.20. User Profile
1.21. Notifications Center
1.22. Organization Settings & Team *(Maps to your Page 23)*
1.23. Audit Log

---

### 2. Page: Login Page
2.1. text input: email/username (story: user types an email or username)
2.2. secure input: password (story: user types a password)
2.3. tick mark: remember me for 7 days (story: sets HttpOnly refresh token cookie lifetime to 7 days)
2.4. button: login (story: submits credentials)
2.5. link: forgot password (story: navigates to recovery flow)
2.6. link: sign up (story: navigates to registration)

### 3. Page: Signup Page
3.1. text input: full name (story: user enters name)
3.2. text input: email (story: user enters email)
3.3. secure input: password (story: user creates password meeting complexity rules)
3.4. secure input: confirm password (story: user re-types password)
3.5. button: create account (story: triggers account creation and verification email)

### 4. Page: Email Verification Page
4.1. text: verification prompt (story: informs user to check email)
4.2. button: resend verification email (story: requests a new time-limited token)

### 5. Page: Forgot Password Page
5.1. text input: email (story: user enters registered email)
5.2. button: send reset link (story: triggers transactional email with reset token)

### 6. Page: Reset Password Page
6.1. secure input: new password (story: user enters new password)
6.2. secure input: confirm new password (story: user confirms new password)
6.3. button: reset password (story: validates token and updates password)

### 7. Page: Main Dashboard
7.1. widget: user counters (story: displays New and Active WOs assigned to user)
7.2. widget: KPI cards (story: shows overdue WOs, open tickets, completion rates)
7.3. chart: work orders by status (story: visualizes planned vs unplanned maintenance)
7.4. chart: safety flag incidents (story: highlights assets with HOT_INSPECT, PAUSE, or STOP flags)

### 8. Page: Zones Management (List & Creation)
8.1. table: zones list (story: displays zones with status and quick actions)
8.2. button: create zone (story: opens form to create a new root or child zone)
8.3. filter: status filter (story: filters zones by Active, Inactive, Under Construction, Decommissioned)

### 9. Page: Zone Detail & Cloning *(Your Page 9)*
9.1. **indicator card: systems count** (story: displays total systems linked to this zone, e.g., "Systems: 3")
9.2. **indicator card: nodes count** (story: displays total service points in this zone, e.g., "Nodes: 5")
9.3. **indicator card: attention required** (story: highlights number of nodes with safety flags or overdue cycles)
9.4. **indicator card: pending tickets** (story: shows count of open/escalated tickets in this zone)
9.5. **indicator card: completed workflows** (story: shows completed WOs for the past day/week)
9.6. form: zone profile (story: edit name, status, address, contact, and up to 5 custom JSONB fields)
9.7. tree view: hierarchy breakdown (story: visualizes the max 2-level breakdown under the zone)
9.8. button: clone zone (story: initiates background cloning job for tree, profiles, cycles, and workflows)

### 10. Page: Systems & Sub-Systems Detail *(Your Page 10)*
10.1. **list: cross-zone engagements** (story: auto-lists other zones this system is linked to via system_zone_links)
10.2. **button: switch to zone** (story: opens or focuses the tab for the primary/selected linked zone)
10.3. **button: expand system** (story: toggles view to show child sub-systems or directly linked nodes)
10.4. form: system profile (story: edit taxonomy, classification, manufacturer, model, serial)
10.5. multi-select: zone links (story: assigns system to multiple zones, marking one as primary)

### 11. Page: Service Points (Nodes) Detail *(Your Page 11)*
11.1. **badge: lifecycle status** (story: visually indicates "Active", "Inactive", or "Decommissioned")
11.2. **badge: hours since last action** (story: displays time elapsed since last WO or counter log)
11.3. **badge: critical notifications** (story: pulsing indicator if node has STOP_UNTIL_COMPLETE or overdue WOs)
11.4. **button: see ticket history** (story: opens a tab/filter showing all repair tickets for this node)
11.5. **button: see maint. history** (story: opens a tab showing past work orders and counter logs)
11.6. **button: see manuals** (story: opens the file manager tab filtered to this node's documents)
11.7. **button: view node cycles** (story: opens cycles tab filtered to this specific node)
11.8. tabs: profile / counters / safety (story: organizes node data into logical sections)
11.9. file uploader: manuals/attachments (story: uploads PDF/TXT/DOCX, enforcing 10MB limit and MIME checks)
11.10. toggle: safety flag (story: Manager/Maintenance sets HOT_INSPECT, PAUSE, or STOP_UNTIL_COMPLETE)

### 12. Page: QR Code Scanner (Mobile View)
12.1. camera viewfinder: HTML5 scanner (story: uses browser camera to scan node QR/barcode)
12.2. text input: manual code entry (story: fallback for typing the QR code)
12.3. view: resolved node data (story: displays node profile and actions based on user role)

### 13. Page: Work Orders List
13.1. table: work orders list (story: displays WOs with status, target asset, deadline)
13.2. filter: role-based view (story: Maintenance sees assigned/pool; Manager sees all org WOs)
13.3. badge: overdue indicator (story: highlights WOs past deadline)

### 14. Page: Workflows & Checklists *(Your Page 14)*
14.1. table: templates list (story: displays workflows and checklists with auto-generated unique codes)
14.2. search: item-level search (story: searches text within individual items inside the templates)
14.3. **button: launch workflow now** (story: manually triggers an immediate work order generation from this template, bypassing cycle timers)
14.4. button: create workflow/checklist (story: opens the editor to build instruction sets)

### 15. Page: Cycles Management *(Your Page 15)*
15.1. table: cycles list (story: displays cycles with target entity, trigger types, and launch mode)
15.2. **button: reset cycle timer** (story: manually resets the counter/calendar evaluation baseline for this cycle)
15.3. **button: pause cycle timer** (story: suspends the cycle, preventing automatic WO generation until resumed)
15.4. form: cycle creation (story: assigns cycle to Zone/System/Node, selects workflow/checklist)
15.5. multi-select: triggers (story: configures Calendar/Cron, Operating Hours, or Operation Count triggers)
15.6. toggle: launch mode (story: sets cycle to Automatic or Manual)

### 16. Page: Checklist/Workflow Editor (with AI)
16.1. form: template metadata (story: edit name, description, and unique code)
16.2. list: work items (story: displays items with activity number, predecessor, measurements)
16.3. button: AI Generate (story: opens AI prompt modal in the Right Side-band to generate draft checklists)
16.4. table: AI draft preview (story: displays generated items for review)
16.5. button: approve/save AI draft (story: saves the reviewed AI output as an active checklist)

### 17. Page: Work Order Execution
17.1. header: WO details & safety flags (story: prominently displays STOP_UNTIL_COMPLETE or other flags)
17.2. list: work items (story: displays snapshot of template items with status)
17.3. input: measurement entry (story: Maintenance enters Numeric, Text, or Boolean readings)
17.4. signature pad: digital signature (story: captures signature when required)
17.5. button: snooze (story: delays WO by 1h, 6h, 12h, 1d, 3d, 6d with mandatory reason)
17.6. button: complete (story: marks all items terminal, releases safety flags, captures cost/downtime)

### 18. Page: Repair Tickets List
18.1. table: tickets list (story: displays tickets with priority, status, and assignment)
18.2. button: create ticket (story: Operator/Manager issues ticket; blocked if org payment is overdue)
18.3. filter: maintenance pool (story: Maintenance users view unassigned OPEN tickets to claim)

### 19. Page: Ticket Detail & Feedback Flow
19.1. header: ticket info & priority (story: displays LOW, MEDIUM, HIGH, CRITICAL priority)
19.2. button: claim (story: Maintenance user claims ticket from pool)
19.3. form: submit report (story: Maintenance submits work performed and findings)
19.4. form: submit feedback (story: Issuer reviews report and sends feedback)
19.5. alert: loop limit warning (story: warns when approaching the 3-loop maximum)
19.6. button: manager decision (story: Manager chooses FORCE_CLOSE, REQUIRE_NEW_TICKET, or MANDATE_ACTION)

### 20. Page: Reports & KPIs
20.1. dashboard: KPI widgets (story: displays overdue WOs, open tickets, downtime)
20.2. filters: date range & asset filters (story: allows Manager/Reporter to narrow down data)
20.3. button: export report (story: triggers background job to generate CSV/XLSX)

### 21. Page: User Profile
21.1. form: personal details (story: edit name, phone, employee ID, timezone)
21.2. button: change password (story: initiates secure password update flow)
21.3. toggle: RTL/LTR layout (story: user overrides system layout direction)

### 22. Page: Notifications Center
22.1. list: recent notifications (story: shows alerts for WO assignments, ticket updates, snooze expirations)
22.2. action: mark as read (story: updates read state and clears badge)
22.3. link: deep navigation (story: clicks notification to open/focus the relevant tab)

### 23. Page: Organization Settings & Team *(Your Page 23)*
23.1. form: organization profile (story: edit logo, contact info, timezone, custom fields)
23.2. display: subscription tier (story: shows Free/Pro/Ultimate tier and active node count vs limit)
23.3. **button: create new user** (story: opens form to send an email invitation to a new user)
23.4. **action: change user role** (story: dropdown to update a team member's role, e.g., Operator to Maintenance)
23.5. **button: remove user from team** (story: deactivates user; system validates no active assignments, open orders, or safety locks exist before allowing removal)
23.6. alert: payment overdue (story: warns that ticket creation is blocked until payment is cleared)

### 24. Page: Audit Log
24.1. table: audit events (story: displays immutable log of critical state changes)
24.2. filters: actor, entity, date (story: allows Manager/SysAdmin to trace specific actions)
24.3. detail view: state diff (story: shows previous state JSON vs new state JSON)
