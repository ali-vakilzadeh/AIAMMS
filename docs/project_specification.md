# MASTER PROJECT SPECIFICATION
## AIAMMS – AI‑Assisted Maintenance Management System
### Functional Specification (MVP)

| Item | Value |
|---|---|
| Document version | 2.0 |
| Date | 2026‑09‑25 |
| Conforms to | `requirements.md` v2.0 (source of truth for scope) |
| Implemented by | `architecture.md` v2.0 |

This document defines **exact behaviour**: business rules, fields, state machines, permissions, formulas, and validation. Requirement IDs in brackets (e.g. `[INV-005]`) trace each rule to `requirements.md`. Terms are defined in the glossary in `requirements.md` §2.

---

## 1. GENERAL CONVENTIONS

1. **Identifiers:** all entities have a UUID `id`. Human‑facing codes/numbers are separate fields.
2. **Tenancy fields:** every tenant‑owned record carries `tenant_id` (root org) and `org_unit_id` (owning org unit).
3. **Audit fields:** `created_at`, `created_by`, `updated_at`, `updated_by`. Business entities also have `deleted_at` (soft delete).
4. **Time:** timestamps are stored in UTC. Date‑only business values (e.g. due date, holiday) are stored as ISO dates, interpreted in the **org unit's timezone**.
5. **Money:** `NUMERIC(20,4)` in the tenant currency. IRR is stored in Rial. Toman is a display option only.
6. **Quantities:** `NUMERIC(18,4)` in the part's stock UoM.
7. **Bilingual names:** fields marked *(fa/en)* store `{ "fa": "...", "en": "..." }`. At least one value is required. The UI shows the user's language, else the other.
8. **Soft delete:** "Delete" in the UI sets `deleted_at`. Records remain for history and are hidden from lists. Hard delete happens only on tenant purge [ORG-015].
9. **Concurrency:** every mutable entity has a `version` integer. Updates send the version they read. A mismatch returns `409 CONFLICT`.

---

## 2. IDENTITY & SESSIONS

### 2.1 User fields [AUTH-007]
| Field | Type | Mandatory | Notes |
|---|---|---|---|
| email | string | ✔ | unique platform‑wide, case‑insensitive |
| password_hash | string | ✔ | Argon2id |
| full_name | string | ✔ | |
| phone_1, phone_2 | string | | E.164 normalized; Iranian local format accepted and normalized |
| employee_id | string | | unique per tenant if set |
| timezone | IANA tz | ✔ | default from org, else `Asia/Tehran` (fa) / `UTC` (en) |
| language | enum fa/en | ✔ | |
| calendar | enum JALALI/GREGORIAN | ✔ | default JALALI for fa, GREGORIAN for en |
| digits | enum PERSIAN/LATIN | ✔ | default PERSIAN for fa |
| avatar_file_id | UUID | | |
| status | ACTIVE / DEACTIVATED | ✔ | |
| email_verified_at | timestamp | | |

### 2.2 Tokens
| Token | Lifetime | Use |
|---|---|---|
| Access JWT | 15 min | Claims: `sub`, `tenant_id`, `active_org_unit_id`, `session_id`, `exp`. Role is **not** trusted from the token. Memberships are resolved server‑side on every request (cached ≤ 60 s). |
| Refresh token | 7 days sliding, rotated on every use | HttpOnly Secure SameSite=Strict cookie. Reuse of a rotated token revokes the whole session family. |
| Email verification | 24 h, single use | |
| Password reset | 1 h, single use | Resetting revokes all sessions. |
| Invitation | 14 days | see §3.5 |

### 2.3 Login protection [AUTH-010]
After 5 failed logins for the same email within 15 min, further attempts are refused for 15 min (response is identical to invalid credentials). Every failure is audited.

### 2.4 Deactivation [AUTH-011]
- Only Managers of an org unit where the user is a member can deactivate them. Owners cannot be deactivated until ownership is transferred.
- On deactivation:
  - Sessions are revoked.
  - Open assignments are listed to the Manager for reassignment.
  - The user remains visible in history as "(deactivated)".

---

## 3. TENANCY, ORG UNITS, MEMBERSHIP & SUBSCRIPTION

### 3.1 Org unit tree [ORG-004]
- Root org unit = tenant. Children = sub‑orgs. Max depth 3 (root = depth 1).
- Org unit fields: name (fa/en), code, parent, logo, address, contact, timezone, language, calendar, currency (root only; inherited), custom fields (2–3), work calendar (§3.7), status (ACTIVE, ARCHIVED).
- Creating a sub‑org requires Owner. The tier must allow another sub‑org [COM-003].
- Archiving a sub‑org:
  - Allowed only if it has no open WOs, tickets, or POs.
  - It becomes read‑only and is hidden from switchers.
  - It can be restored by the Owner within 30 days.
  - After 30 days it stays archived (read‑only history).
- Records never move between org units in MVP. Moving an asset to another sub‑org = decommission + import.

### 3.2 Membership [ORG-006, ORG-009, RBAC-004]
Membership = (user, org_unit, role, inherit_to_descendants: bool, zone_scope: set of zone IDs or ALL).

**Effective access** of a user to org unit U:
1. A direct membership on U gives that role.
2. Otherwise, the nearest ancestor membership with `inherit_to_descendants = true` gives that role.
3. Otherwise there is no access, except consolidated aggregates (§3.3).

If several apply, the direct membership wins. A user has one role per org unit.

**Zone scope** restricts visibility and actions to records whose zone is within scope (zone subtree included):
- Assets and their WOs, tickets and readings.
- Storerooms located in scoped zones.
- Systems, if at least one linked zone is in scope.

Templates, parts master, and vendors are not zone‑scoped.

### 3.3 Consolidated view [ORG-007, RPT-004]
A Manager or Reporter membership on org unit P (without inherit) lets the user see **aggregated KPIs** across P's descendants: counts, sums, and rates grouped by sub‑org. Drill‑down to records requires effective access to that sub‑org.

### 3.4 Active context
- The UI works in one **active org unit** at a time (switcher in header).
- Lists show records of the active unit only. A Manager/Reporter with inherited access may tick "include sub‑orgs" on list and report pages.

### 3.5 Invitations [ORG-011, ORG-012]
- Fields: email, org_unit, role, inherit flag, zone scope, invited_by, token hash, expires_at, status.
- States: PENDING → ACCEPTED | EXPIRED (after 14 days, by scheduler) | REVOKED (by Manager).
- An existing user belonging to **another tenant** sees the invitation. They must leave the current tenant first [ORG-010].
- An existing user in the **same tenant** gets the membership added immediately on acceptance.

### 3.6 Subscription & payment [COM-003..009]
- Subscription fields (tenant): tier, effective_from, effective_to, trial_ends_at, payment_state, asset_quota_allocations {org_unit_id: n}.
- **Asset count** = assets in the tenant where `lifecycle_status != DECOMMISSIONED AND deleted_at IS NULL`.
- The check runs on: create, restore, recommission, import commit, zone clone. If the result would exceed the limit, the operation is refused with `TIER_LIMIT_REACHED` and the count, limit, and upgrade link.
- **Quota allocation:** if sub‑org S has an allocation, S's own count (including its descendants) may not exceed it. The sum of allocations may not exceed the tier limit.
- Payment state transitions: CURRENT → OVERDUE (invoice unpaid past due date) → SUSPENDED (after configurable days, default 30) → CURRENT (payment).
  - OVERDUE blocks `ticket.create` only.
  - SUSPENDED blocks every write except payment, data export, and profile.
- Self‑hosted edition: `TIER_ENFORCEMENT=false` disables all tier and payment checks.

### 3.7 Work calendar [ORG-016]
- Fields: working weekdays, shifts (name, start, end; may cross midnight), holidays (date, name fa/en, org unit), timezone.
- Default for fa tenants: Saturday–Wednesday full days, Thursday optional half day, Friday weekend. The official holiday list for the current Jalali year is pre‑loaded.
- Sub‑orgs inherit the calendar and may override it.
- Used by: cycle due‑date adjustment (§10.6), SLA working‑time clocks (§15.6), automatic launch slots (§10.8).

---

## 4. PERMISSION MATRIX [RBAC-006]

Legend:
- ✔ = allowed within the active org unit and zone scope.
- ◐ = allowed on own/assigned records only.
- R = read only.
- — = not allowed.
- Columns: **M** Manager, **Rp** Reporter, **O** Operator, **Mt** Maintenance, **S** Storekeeper.
- The **Owner**‑only actions are marked (Owner).

| Area | Action | M | Rp | O | Mt | S |
|---|---|---|---|---|---|---|
| Org | Edit org unit profile, work calendar, settings | ✔ | — | — | — | — |
| Org | Create/archive sub‑org, subscription, billing, ownership transfer, AI data consent (Owner) | Owner | — | — | — | — |
| Org | Invite users, change roles/scope, deactivate | ✔ | — | — | — | — |
| Org | View member directory | ✔ | R | R | R | R |
| Assets | Create/edit/move/decommission zones, systems, assets, asset classes | ✔ | R | R | R | R |
| Assets | Edit asset technical fields, attach documents/photos | ✔ | — | — | ✔ | — |
| Assets | Restore deleted, clone zone, recommission | ✔ | — | — | — | — |
| Assets | Install/remove component | ✔ | — | — | ✔ | — |
| Assets | Print QR labels | ✔ | ✔ | — | ✔ | ✔ |
| Assets | Set operating state manually (stopped/running) | ✔ | — | ✔ | ✔ | — |
| Meters | Log reading | ✔ | — | ✔ | ✔ | — |
| Meters | Correct reading, replacement, rollover | ✔ | — | — | — | — |
| Meters | Baseline reset | ✔ | — | — | ✔ | — |
| Cycles | Create/edit/suspend/activate | ✔ | R | — | R | — |
| Cycles | Manual launch / advance | ✔ | ✔ | — | — | — |
| Templates | Create/edit drafts | ✔ | — | — | — | — |
| Templates | Publish/retire version | ✔ | — | — | — | — |
| Templates | Suggest edits on drafts (incl. AI drafts) | ✔ | ✔ | — | ✔ | — |
| Templates | View | ✔ | R | R | R | R |
| WO | Create manual WO | ✔ | — | — | ✔ | — |
| WO | Assign/reassign, cancel, change deadline/priority | ✔ | — | — | — | — |
| WO | View | ✔ | R | ◐ (assigned + WOs on assets in scope) | ✔ | R |
| WO | Execute items, measurements, labour, signatures, comments | ✔ | — | ◐ | ◐ | — |
| WO | Snooze, reject, put on hold, complete | ✔ | — | ◐ | ◐ | — |
| WO | QC approve / return | ✔ (or designated reviewer) | — | — | — | — |
| WO | Save as template | ✔ | — | — | — | — |
| Safety | Override/clear safety flag | ✔ | — | — | — | — |
| Tickets | Create | ✔ | — | ✔ | — | — |
| Tickets | View | ✔ | R | ◐ (own + in scope) | ✔ | — |
| Tickets | Claim | — | — | — | ✔ | — |
| Tickets | Assign/reassign | ✔ | — | — | — | — |
| Tickets | Submit report | ✔ | — | — | ◐ | — |
| Tickets | Accept / return feedback | ◐ (as issuer) + on behalf after timeout | — | ◐ (as issuer) | — | — |
| Tickets | Convert to WO | ✔ | — | — | ✔ | — |
| Tickets | Escalation decision | ✔ | — | — | — | — |
| Reliability | Maintain failure codes | ✔ | — | — | — | — |
| Reliability | Record/edit downtime | ✔ | — | ✔ | ✔ | — |
| Inventory | Parts master, UoM, storerooms, bins, reorder policy | ✔ | R | R | R | ✔ |
| Inventory | View stock | ✔ | R | R | R | ✔ |
| Inventory | Issue/return to WO or ticket | ✔ | — | — | ◐ (self‑issue storerooms only) | ✔ |
| Inventory | Transfer | ✔ | — | — | — | ✔ |
| Inventory | Adjustment ≤ threshold | ✔ | — | — | — | ✔ |
| Inventory | Adjustment > threshold (approve) | ✔ | — | — | — | — |
| Inventory | Cycle count create/enter | ✔ | — | — | — | ✔ |
| Inventory | Cycle count approve | ✔ | — | — | — | ✔ (variance ≤ threshold) |
| Purchasing | Vendors | ✔ | R | — | R | ✔ |
| Purchasing | Create requisition | ✔ | — | — | ✔ | ✔ |
| Purchasing | Approve requisition | ✔ | — | — | — | — |
| Purchasing | Create/edit/send PO | ✔ | — | — | — | ✔ |
| Purchasing | Approve PO (within threshold) | ✔ | — | — | — | — |
| Purchasing | Receive / return to vendor | ✔ | — | — | — | ✔ |
| Reporting | Personal dashboard | ✔ | ✔ | ✔ | ✔ | ✔ |
| Reporting | Org dashboards, KPIs, exports | ✔ | ✔ | — | — | inventory & purchasing only |
| Reporting | Scheduled reports | ✔ | ✔ | — | — | — |
| Reporting | Audit log UI | ✔ | ✔ | — | — | — |
| Comms | Announcements | ✔ | — | — | — | — |
| Data | Import (all entities) | ✔ | — | — | — | parts, storerooms, stock, vendors |
| AI | Manual assistant | ✔ | ✔ | ✔ | ✔ | ✔ |
| AI | Generate template drafts | ✔ | ✔ | — | — | — |
| AI | Approve AI template drafts | ✔ | — | — | — | — |
| AI | Troubleshooting suggestions | ✔ | — | R | ✔ (approve plan) | — |
| AI | View/correct training log | ✔ | — | — | — | — |
| AI | AI settings (enable, privacy mode) | Owner | — | — | — | — |
| MCP | Manage API keys | ✔ | — | — | — | — |
| MCP | Approve pending MCP actions | whoever holds permission for the underlying action | | | | |

The **SYS_ADMIN** has no tenant permissions by default. It acts through audited support sessions only [RBAC-007].

---

## 5. LOCALIZATION RULES [I18N-*]

### 5.1 Calendars
- Jalali ↔ Gregorian conversion follows the standard arithmetic Solar Hijri calendar.
- Jalali months:
  - Farvardin–Shahrivar: 31 days.
  - Mehr–Bahman: 30 days.
  - Esfand: 29 days, or 30 in leap years.
- The display calendar is per user. Recurrence rules carry their own calendar (§10.3).
- Week start: Saturday (fa) / Monday (en). Configurable per user.

### 5.2 Digits & text normalization
- Input normalization (all text and numeric fields):
  - Persian (۰–۹) and Arabic‑Indic (٠–٩) digits → Latin for storage in numeric fields.
  - Arabic ي → Persian ی, ك → ک.
  - Trim spaces.
  - Keep ZWNJ in stored text.
- Search normalization additionally removes diacritics (fatha, kasra, etc.), treats ZWNJ as a word joiner, and folds ة/ه and أ/إ/ا.
- Display: numbers shown in user's digit style, with locale separators (fa: `٬` thousands, `٫` decimal).
- **Codes** (asset codes, SKUs, WO numbers, serials) are always shown in Latin digits, in an LTR isolate.

### 5.3 Bidirectional text
- Mixed strings are rendered with Unicode isolates (`<bdi>` / `dir="auto"`).
- Tables align columns according to the UI direction. Numeric columns are always right‑aligned in LTR and left‑aligned in RTL, with LTR isolation.

### 5.4 Document numbering
Format `{PREFIX}-{YEAR}-{SEQ:6}`:
- `YEAR` is the Jalali or Gregorian year per org unit calendar.
- The sequence is per org unit, per document type, per year.

| Document | Default prefix |
|---|---|
| Work order | WO |
| Ticket | TK |
| Purchase requisition | PR |
| Purchase order | PO |
| Receipt | GR |
| Cycle count | CC |
| Stock adjustment | ADJ |

Prefixes are editable by Managers. Numbers are never reused. Cancelled documents keep their number.

---

## 6. ZONES (LOCATIONS) [LOC-*]

| Field | Mandatory | Notes |
|---|---|---|
| name (fa/en) | ✔ | |
| code | ✔ | unique per org unit; auto‑suggested |
| parent_zone_id | | depth ≤ 3 |
| status | ✔ | ACTIVE, INACTIVE, UNDER_CONSTRUCTION, DECOMMISSIONED |
| address | ✔ for top‑level zones | sub‑zones inherit unless overridden |
| contact (name, phone, email) | ✔ for top‑level zones | inherited like address |
| description | | |
| latitude, longitude | | |
| custom_fields | | ≤ 5, defined per org unit (key, label fa/en, type: text/number/date/select) |

**Rules:**
- Z1: Decommissioning a zone requires that it has no ACTIVE assets (they must be moved or decommissioned first).
- Z2: The root zone created from the org profile [ORG-003] cannot be deleted.
- Z3: **Zone clone** [LOC-004]:
  - Runs as a background job: PENDING → PROCESSING (progress %) → COMPLETED | FAILED (no partial result; transaction per clone).
  - Clones receive new IDs. Codes get a suffix (`-C1`, or a user‑supplied prefix/suffix rule).
  - Meters are created at 0 with no readings. No WOs, tickets, stock or history are cloned.
  - The tier check is performed before start.

---

## 7. SYSTEMS [SYS-*]

| Field | Mandatory | Notes |
|---|---|---|
| name (fa/en), code | ✔ | code unique per org unit |
| parent_system_id | | only one level (sub‑system) |
| classification | ✔ | from tenant taxonomy |
| zone links | ✔ ≥ 1 | exactly one `is_primary` |
| criticality/priority | ✔ | LOW, MEDIUM, HIGH, CRITICAL |
| spec fields | | generic key/value with units |
| status | ✔ | ACTIVE, INACTIVE, DECOMMISSIONED |

A system's **derived state** is "impaired" when any member asset is STOPPED. It is shown on the system page and dashboards.

---

## 8. ASSETS [AST-*]

### 8.1 Fields
| Field | Mandatory | Notes |
|---|---|---|
| name (fa/en) | ✔ | |
| code | ✔ | unique per org unit (non‑deleted) |
| asset_class_id | ✔ | |
| zone_id | ✔ | location |
| position_text | | free text, e.g. "Mezzanine, bay 3" |
| system_id | | system or sub‑system |
| parent_asset_id | | physical containment |
| manufacturer, model, serial_number, year | | |
| install_date, purchase_date, purchase_cost, vendor_id | | |
| warranty_expiry | | drives warranty badge [AST-015] |
| criticality | ✔ | A, B, C (default from class) |
| priority | ✔ | LOW, MEDIUM, HIGH, CRITICAL |
| lifecycle_status | ✔ | ACTIVE, INACTIVE, DECOMMISSIONED |
| operating_state | ✔ (system‑maintained) | RUNNING, RESTRICTED, STOPPED, IN_MAINTENANCE |
| spec fields | | from class template + free key/value |
| qr_token | ✔ (auto) | |
| rotable_part_id + serial | | when asset is a serialized rotable part [INV-013] |

### 8.2 Relationship rules
- **A1** Zone is mandatory. A component's `zone_id` always equals its parent's. Setting a parent copies the parent's zone. Changing the parent's zone updates all descendants in the same transaction.
- **A2** Nesting depth ≤ 4, and an asset can never be its own ancestor.
- **A3** System membership is independent of parent. A component defaults to its parent's system but may be set differently (e.g. the motor belongs to "Electrical Drives").
- **A4** The asset's zone must be linked to its system (if the zone is not yet linked, the link is added automatically after confirmation).
- **A5** Parent and child must belong to the same org unit.

### 8.3 Lifecycle transitions [AST-005, AST-011, AST-012]
| From | To | Who | Conditions / effects |
|---|---|---|---|
| (new) | ACTIVE / INACTIVE | M | tier check |
| ACTIVE | INACTIVE | M | open PM WOs remain; no new PM WOs generated |
| INACTIVE | ACTIVE | M | no tier check (INACTIVE assets already count); cycles resume from this date |
| ACTIVE/INACTIVE | DECOMMISSIONED | M | Must have no open WOs/tickets (the dialog offers to cancel them with a reason). Components: cascade decommission, or detach first. Cycle instances deactivated. Reservations released. |
| DECOMMISSIONED | ACTIVE | M | "Recommission", reason required, tier check |
| any | deleted | M | = decommission + `deleted_at`; restorable 30 days |
| deleted (≤ 30 d) | ACTIVE | M | restore (with components deleted in the same operation), tier check, cycles resume from restore date |

### 8.4 Move, install, remove [AST-007, AST-008]
- **Move:** change zone and/or parent and/or position. The history entry records from/to values and a reason.
- **Remove component:**
  - Sets `parent_asset_id = null`.
  - Asks for the new zone (e.g. workshop) and new lifecycle (INACTIVE by default).
  - If the asset is a rotable, it may instead be returned to stock (§17.10).
- **Install component:** set parent. The history entry records "installed in X at position Y".
- The asset page shows an **installation history**: which component assets occupied it over time.

### 8.5 BOM [AST-009]
- BOM lines: part, quantity, UoM, note, source (ASSET or CLASS).
- The effective BOM = class BOM lines + asset lines. Asset lines may hide class lines.

### 8.6 QR [AST-010]
- `qr_token`: 12‑char random base32, unique platform‑wide, and never re‑issued. It encodes the URL `https://{host}/q/{qr_token}`.
- Resolution requires authentication. If the user has no access, the response is "Not found" (no existence leak).
- Labels: QR, code (Latin), name (user language), zone name, optional logo.
- Label sizes: 25×25, 50×30, 70×40 mm; A4 sheet layouts.
- Batch printing: by zone, system, class, or selection.
- The asset code is also rendered as a Code128 barcode on labels ≥ 50 mm.

---

## 9. METERS [MTR-*]

### 9.1 Meter fields
- asset, type (OPERATING_HOURS, OPERATION_COUNT, DISTANCE, GENERIC), unit, name, current_lifetime_value (derived), max_rate_per_day (plausibility), rollover_value (optional), derived_from_meter_id (optional), status.

### 9.2 Readings
- Reading: value (absolute) or delta, reading_at (≤ now), source, entered_by, note.
- **Monotonic rule:** an absolute reading < previous lifetime value is rejected, unless:
  - (a) the meter has `rollover_value` → delta = (rollover_value − previous) + value; or
  - (b) the user records a **meter replacement** (old final value, new start value). Lifetime = sum across segments.
- **Plausibility** [MTR-004]: if (Δvalue / Δdays) > max_rate_per_day, the user must confirm. The reading is flagged `suspicious`.
- **Back‑dated reading** (reading_at earlier than the latest reading): allowed only if it lies between neighbours in value. Otherwise rejected.
- **Derived meters** [MTR-005]: they have no own readings. Their values mirror the source meter from the moment of linking (offset stored).
- **Corrections** (Manager): void a reading with a reason. Triggers are re‑evaluated.

### 9.3 Baselines [MTR-006]
- For every (cycle instance, meter) pair the system stores `baseline_value` = the lifetime reading at the last service.
- Since‑last‑service = current lifetime − baseline.
- Completing a WO generated by that cycle sets the baseline:
  - to the reading entered at completion, if the completion form requires one (mandatory when the cycle has a meter trigger);
  - FIXED basis: `baseline = previous baseline + interval`.
- **Manual baseline reset** (Maintenance/Manager):
  - Sets the baseline to the current reading (reason required).
  - Scope: asset only, or asset + selected components.
  - Audited.

---

## 10. MAINTENANCE CYCLES [PM-*]

### 10.1 Cycle fields
| Field | Notes |
|---|---|
| code, name (fa/en), description | code unique per org unit |
| target_type, target_id | ZONE, SYSTEM, SUB_SYSTEM, ASSET |
| scope_mode | SELF, EACH_DESCENDANT |
| class_filter | asset classes (EACH_DESCENDANT only) |
| template_type, template_version_id | checklist or workflow (published version, or "latest published" auto‑follow flag) |
| work_type | PREVENTIVE / INSPECTION / PREDICTIVE |
| priority, safety_flag, safety_propagation | STOP_PARENTS (default) / RESTRICT_PARENTS |
| estimated_duration, planned_parts[], planned_crafts[] | |
| assignee | user / role pool / team |
| scheduling_basis | FIXED / FLOATING |
| lead_time | duration (calendar) and/or meter units |
| grace_period | duration |
| deadline_behavior | FLAG_CRITICAL_STOP / WAIT_UNTIL_COMPLETED |
| launch_mode | AUTOMATIC / MANUAL |
| launch_slots | 1 or 2 local times (default: start of shift 1; optionally shift 2) |
| non_working_day_rule | KEEP / PREVIOUS_WORKING_DAY / NEXT_WORKING_DAY |
| open_wo_policy | SKIP_IF_OPEN (default) / ALWAYS_GENERATE |
| influence_children | bool (lock) |
| nesting_group_id, nesting_rank | §10.11 |
| status | ACTIVE, SUSPENDED, ARCHIVED |

### 10.2 Cycle instances
Every (cycle, target asset) pair has a **cycle instance** holding:
- next due point(s)
- meter baselines
- overrides (interval/trigger values, when allowed)
- last generated WO
- last completion

For SELF, there is one instance. For EACH_DESCENDANT, instances are created or removed automatically as matching ACTIVE descendants appear or disappear.

### 10.3 Triggers
| Type | Parameters | Due condition |
|---|---|---|
| CALENDAR | recurrence rule: `{calendar: JALALI\|GREGORIAN, freq: DAILY\|WEEKLY\|MONTHLY\|YEARLY, interval, by_weekday[], by_month_day[] (1..31, −1 = last), by_month[], time_of_day}` | now ≥ next_due − lead_time |
| METER | meter type/name (resolved per asset), interval | (lifetime − baseline) ≥ interval − lead_units |
| SEASONAL | calendar, window start (month, day), window end (month, day), generate_at: WINDOW_START / OFFSET_DAYS | now ≥ window start (+ offset) − lead_time, and not yet generated in this window |

- If `by_month_day` does not exist in a month (e.g. 31 in Mehr), the last day of the month is used.
- A seasonal WO's due date = window end, unless the grace settings produce an earlier deadline.
- Raw cron expressions are **not** exposed to users. The rule builder covers all cases above.

### 10.4 Winner & restart [PM-004, PM-005]
- The first satisfied trigger generates the WO. The WO stores `winning_trigger_id` and the due point.
- On completion of that WO, all triggers of the instance restart:
  - **FLOATING:** calendar anchor = completion time; meter baselines = readings at completion.
  - **FIXED:** calendar anchor = the due point of the WO; meter baseline = previous baseline + interval (for the winning meter trigger), and the reading at completion for other meter triggers.
- A **cancelled** WO (not completed) restarts the triggers as FIXED from its due point.

### 10.5 Due & deadline
- Due date = the calendar due point, adjusted by the non‑working‑day rule. For meter triggers, due date = generation time + estimated usage interval (or + grace, if no usage history).
- Deadline = due date + grace_period.

### 10.6 Non‑working days [PM-007]
The rule is applied using the org unit work calendar (§3.7).

### 10.7 Open WO policy
With `SKIP_IF_OPEN`, when the instance is due but its previous WO is still open (not COMPLETED/CLOSED/CANCELLED):
- no new WO is created;
- an evaluation record `SKIPPED_OPEN_WO` is written;
- the assignee and the Manager are notified once.

### 10.8 Launch modes [PM-010]
- **AUTOMATIC:**
  - Calendar and seasonal triggers are evaluated at each launch slot (org unit local time).
  - Meter triggers are evaluated immediately when a reading is saved, and also at launch slots.
- **MANUAL:**
  - Satisfied instances appear in "Due for launch" with their due date.
  - Launching (Manager/Reporter) generates the WO.
  - Unlaunched items past their deadline follow the deadline behaviour and are marked overdue.

### 10.9 Manual advance [PM-011]
- "Launch now" generates the WO immediately, even if not yet due.
- The resulting WO's due point = now. The next due is computed by the basis as usual.

### 10.10 Missed evaluations [PM-009]
- If the scheduler was down and one or more due points were passed, the next evaluation generates **one** WO for the latest missed due point, marked `overdue_on_creation = true`.
- Earlier missed due points are recorded as `MISSED` evaluations (they count as non‑compliant in PM compliance).

### 10.11 Nesting / suppression [PM-015]
Cycles in the same nesting group on the same target are ranked (higher rank = larger job).

When an instance of rank r becomes due, any lower‑rank instance with a due point within the group tolerance (default ±7 days or ±10% of interval):
- is **suppressed** (evaluation `SUPPRESSED_BY` pointing to the higher WO);
- restarts as if completed together with the higher‑rank WO.

The higher‑rank template should include the lower‑rank tasks. This is a Manager responsibility, and the UI warns if it doesn't.

### 10.12 Suspension [PM-012]
- SUSPENDED: no evaluation.
- On activation: calendar anchors = activation time (FIXED and FLOATING alike). Meter baselines are unchanged, and the next evaluation applies normally.

### 10.13 Inheritance [PM-013]
- EACH_DESCENDANT cycles create instances on matching descendants.
- On a descendant instance, a Manager can override: interval values, lead time, assignee, template (to another published version of the same template family). This is allowed only if `influence_children = false`.
- A descendant may also **opt out** (instance disabled), again only if the cycle is not locked.
- Parent cycle changes propagate to all non‑overridden fields of instances, and affect only future WOs [PM-014].

### 10.14 Evaluation records & idempotency [PM-018]
- Every evaluation writes `(cycle_instance_id, due_point, trigger_id, result: GENERATED | SKIPPED_OPEN_WO | SUPPRESSED | MISSED | NOT_DUE | ERROR, wo_id)`.
- A unique constraint on `(cycle_instance_id, due_point)` for GENERATED guarantees no duplicates.

---

## 11. SAFETY FLAGS & OPERATING STATE [SAF-*]

### 11.1 Operating‑state causes
An asset's operating state is computed from its active **state causes**:

| Cause | Created when | Removed when | State on asset | State on ancestors |
|---|---|---|---|---|
| WO_PAUSE | WO with PAUSE_FOR_INSPECTION → IN_PROGRESS | WO completed / cancelled / Manager override | IN_MAINTENANCE | RESTRICTED |
| WO_STOP | WO with STOP_UNTIL_COMPLETE → IN_PROGRESS | same | IN_MAINTENANCE | STOPPED (STOP_PARENTS) or RESTRICTED (RESTRICT_PARENTS) |
| DEADLINE_STOP | WO deadline passed with FLAG_CRITICAL_STOP | WO completed / Manager override | STOPPED | per propagation setting |
| MANUAL_STOP | user sets asset stopped (with reason), or ticket "asset stopped" | user sets running | STOPPED | — (no propagation) |
| MANUAL_RESTRICT | user sets restricted | user clears | RESTRICTED | — |
| WO_WORK | WO without flag or with HOT_INSPECT, IN_PROGRESS | — | *no change* (HOT_INSPECT = running) | — |

**Precedence:** STOPPED > IN_MAINTENANCE > RESTRICTED > RUNNING. No active causes = RUNNING.

### 11.2 Rules
- Only safety‑flag causes propagate to ancestors [SAF-003]. Propagation walks the physical parent chain.
- Clearing a flag cause:
  - Happens automatically on WO completion/cancellation.
  - Manually, only a Manager can clear it ("override", mandatory reason, audited, notification to assignee).
  - An MCP agent cannot clear a human‑created cause [MCP-008].
- **Downtime linkage** [SAF-005]:
  - Transition into STOPPED or IN_MAINTENANCE opens a downtime event (type PLANNED for WO_PAUSE/WO_STOP, UNPLANNED for DEADLINE_STOP/MANUAL_STOP).
  - Transition out closes it.
  - RESTRICTED does not create downtime; it is tracked as "restricted time".
- **Permits** [SAF-007]:
  - An item with `permit_required` cannot move to IN_PROGRESS until a permit record exists: permit type (LOTO, HOT_WORK, CONFINED_SPACE, WORK_AT_HEIGHT, ELECTRICAL, OTHER), number, issuer, isolation points confirmed (checkbox list), time.
  - Permit closure is recorded at item completion.

---

## 12. CHECKLISTS & WORKFLOWS [WF-*]

### 12.1 Templates and versions [WF-008]
- **Template family:** code (unique per org unit), name (fa/en), type (CHECKLIST/WORKFLOW), asset class hints, available_to_sub_orgs flag [WF-011].
- **Version:** number, state DRAFT → PUBLISHED → RETIRED, change note, published_by/at, `ai_generated` flag and `ai_draft_id`.
- Only one DRAFT per family at a time. Publishing a new version doesn't change existing WOs. Cycles with "auto‑follow latest" use the new version for future WOs.
- A RETIRED version cannot be assigned to new cycles. Cycles still using it are listed for the Manager.
- A DRAFT can only be published by a Manager, and must pass validation (§12.3).

### 12.2 Checklist [WF-004]
- An ordered flat list of items.
- Result per item: INSPECTED, PASS, FAIL, and N/A (only if `allow_na`).
- If the item has a numeric measurement with thresholds, PASS/FAIL is automatic (§12.6).

### 12.3 Workflow graph [WF-005..007]
A workflow version is a directed acyclic graph of nodes:

| Node | Meaning |
|---|---|
| TASK | executable step (item) |
| AND_SPLIT | all outgoing branches start (parallel) |
| AND_JOIN | waits for all incoming branches |
| DECISION | exactly one outgoing branch is taken, chosen by ordered conditions. The last branch is `ELSE` (mandatory). |
| MERGE | joins alternative branches (after DECISION) |
| END | completion |

Sequential workflows are simply chains of TASK nodes (M2). The editor offers a list view for chains and a graph view for splits and decisions (M4).

**Validation on publish:**
- The graph is acyclic.
- There is exactly one start (the first node) and every path reaches END.
- Every AND_SPLIT is matched by an AND_JOIN.
- Every DECISION has an ELSE branch and is matched by a MERGE.
- Conditions reference only tasks that are guaranteed to have completed before the decision.

**Condition grammar:**
```
condition := clause ( ("AND" | "OR") clause )*
clause    := ref op value | ref "IS" ("PASS"|"FAIL"|"COMPLETED"|"FAILED"|"EMPTY")
ref       := "task[" activity_no "]." ("result" | "measurement" | "measurement." name)
op        := "<" | "<=" | ">" | ">=" | "==" | "!=" | "IN"
```
If a referenced value is empty, the clause evaluates to false, so ELSE is taken. The editor provides a form builder. The grammar is the stored format.

### 12.4 Work item fields [WF-013]
T = defined in the template; E = captured at execution.

| Group | Field | T/E | Mandatory |
|---|---|---|---|
| Identification | activity_no (auto, editable), node type | T | ✔ |
| Identification | predecessors (derived from graph) | T | ✔ (auto) |
| Content | description (fa/en), detailed instructions (rich text), attachments/images | T | description ✔ |
| Measurement | measurement type NUMERIC/TEXT/BOOLEAN, name, unit, min, max, required flag | T | if measured |
| Scheduling | planned offset from WO start, estimated duration | T | |
| Resources | required crafts/skills, certifications, tools, parts (part + qty) | T | |
| Safety | safety flag, permit required + type, risk level (LOW/MED/HIGH) | T | |
| Control | signature required, allow N/A, on_fail behaviour (CONTINUE / STOP_WORKFLOW) | T | defaults: no/no/CONTINUE |
| Location | location override (zone/asset/position text) | T/E | |
| Execution | status, result, measurement value, performed_by, started_at, completed_at, actual duration, comment, photos, signature, permit record | E | status ✔; result ✔ to complete; value ✔ if required; comment ✔ if FAIL/override |
| Assignment | assigned_to (user/role) override per item | E | |
| Impact | downtime impact (none/partial/full), cost note | E | |
| Links | linked ticket, follow‑up WO | E | |
| Quality | quality_checked_by, at | E | if QC required |

### 12.5 Item execution states
PENDING (predecessors not complete) → READY → IN_PROGRESS → COMPLETED | FAILED.
- SKIPPED: the branch was not taken, or the item was N/A.
- HALTED: blocked, e.g. permit refused or safety condition. A reason is required. Can be resumed to READY.
- "Performed by" is a **field**, not a state.
- `on_fail = STOP_WORKFLOW`: all remaining items become SKIPPED and the WO outcome becomes FAILED. The executor must complete the WO or raise a follow‑up.

### 12.6 Automatic pass/fail [WF-010]
- For NUMERIC items with min and/or max: value within [min, max] → PASS, otherwise FAIL.
- BOOLEAN items: `true` = PASS unless inverted in the template.
- The executor may override the automatic result with a mandatory reason. The override is flagged in the report.

### 12.7 Save as template [WF-012]
Copies the WO's snapshot (items, graph, planned parts/crafts, actual durations as new estimates) into a new family, or into a new DRAFT version of the source family.

---

## 13. WORK ORDERS [WO-*]

### 13.1 Fields
| Field | Notes |
|---|---|
| number | §5.4 |
| work_type | PREVENTIVE, INSPECTION, CORRECTIVE, EMERGENCY, PREDICTIVE, PROJECT |
| source | CYCLE, TICKET, MANUAL, QR, MCP, FOLLOW_UP |
| source refs | cycle_instance_id + due_point, ticket_id, parent_wo_id |
| target | zone / system / asset |
| title (fa/en), description | |
| snapshot | template version id + frozen item/graph copy |
| priority | LOW…CRITICAL |
| safety_flag | max of items and cycle |
| dates | issued_at, planned_start, due_at (deadline), started_at, completed_at, closed_at, stopped_at |
| assignment | lead user, additional assignees, role pool or team |
| status, outcome | §13.2; outcome SUCCESS / PARTIAL / FAILED |
| overdue (derived) | `now > due_at AND status ∈ {OPEN, ACKNOWLEDGED, IN_PROGRESS, ON_HOLD, SNOOZED, REJECTED}` |
| acknowledged_by/at | first view by an assignee |
| hold_reason, snooze_until, snooze_reason | |
| QC | qc_required, qc_reviewer, qc_result |
| cost (derived) | labour, parts, external, total |
| failure codes | problem, cause, action (CORRECTIVE/EMERGENCY) |
| downtime links | |
| warranty flag (derived) | |
| AI | ai_suggestions_used |

### 13.2 State machine [WO-006]
| From | Event | To | Who | Rules |
|---|---|---|---|---|
| — | generate/create | OPEN | system / M / Mt | reservations created for planned parts |
| OPEN | first view by assignee | ACKNOWLEDGED | assignee | idempotent |
| OPEN / ACKNOWLEDGED | start (first item started) | IN_PROGRESS | assignee / M | safety causes activate (§11) |
| OPEN / ACKNOWLEDGED / IN_PROGRESS | hold (reason code) | ON_HOLD | assignee / M | safety causes stay active |
| ON_HOLD | resume / parts received | previous state | assignee / M / system | |
| OPEN / ACKNOWLEDGED | snooze (duration, reason) | SNOOZED | assignee / M | not allowed if the snooze end > deadline for STOP_UNTIL_COMPLETE WOs |
| SNOOZED | snooze expires / resume | ACKNOWLEDGED | system / assignee | notification sent |
| OPEN / ACKNOWLEDGED / SNOOZED | reject (reason) | REJECTED | assignee | Manager notified |
| REJECTED | reassign | OPEN | M | |
| any open state | cancel (reason) | CANCELLED | M | reservations released; safety causes removed; cycle restarts (§10.4) |
| IN_PROGRESS | complete | COMPLETED | assignee / M | §13.3 |
| COMPLETED | QC approve / auto (no QC) | CLOSED | reviewer / system | without QC: auto‑close after 72 h, or immediately by M |
| COMPLETED | QC return (reason) | IN_PROGRESS | reviewer | |
| COMPLETED | reopen (reason) | IN_PROGRESS | M / assignee (≤ 72 h, no QC done) | |

**Snooze durations:** 1 h, 6 h, 12 h, 1 d, 3 d, 6 d. Snoozing does **not** change `due_at`.

### 13.3 Completion rules [WO-012]
1. Every non‑SKIPPED item has a terminal state (COMPLETED/FAILED).
2. Required measurements are filled in.
3. Failed items and overrides have comments.
4. Required signatures are captured.
5. A meter reading is entered, if the source cycle has a meter trigger.
6. Failure codes are entered for CORRECTIVE/EMERGENCY (problem code mandatory, configurable).
7. Open labour timers are stopped.
8. Outcome: all PASS/COMPLETED → SUCCESS; any FAILED but workflow finished → PARTIAL; stopped by `on_fail` → FAILED.
9. After completion, labour/parts/external costs can still be added until CLOSED.
10. **Closed WOs are immutable.** Corrections are made by adding comments or linked records.

### 13.4 Follow‑up [WO-013]
From any FAILED item or at completion, the user can:
- create a CORRECTIVE follow‑up WO (Maintenance/Manager), or
- a ticket (Operator/Manager),
pre‑filled with the asset, item description, and measurement. The link is stored both ways.

### 13.5 Signatures [WO-016]
- Record: user id, full name, role, timestamp, signature image (drawn), SHA‑256 of the canonical JSON of the signed content (item or WO completion data), and IP.
- Changing the signed content afterwards is impossible, because the item is locked after signing.

### 13.6 Cost roll‑up [WO-015, AST-014]
- Labour = Σ(hours × rate × multiplier).
- Parts = Σ(ISSUE value) − Σ(RETURN value).
- External = Σ external lines + direct‑charge PO receipts.
- Asset cost roll‑up for a period = Σ costs of WOs and tickets targeting the asset (+ its components if selected), by completion date.

---

## 14. LABOUR [LAB-*]

- **Craft:** name (fa/en), default hourly rate.
- **User crafts:** list, plus optional personal rate override.
- Overtime multiplier per org unit (default 1.4).
- **Labour entry:** WO or ticket, user, craft, start, end or duration, type (REGULAR/OVERTIME), note.
  - Entered by the user themselves, or by a Manager for others.
  - The mobile timer creates the entry on stop.
  - Overlapping entries for the same user are warned, not blocked.
- **Teams:** name, members, lead. Assigning a WO to a team makes it visible to all members. The first member to acknowledge becomes lead unless the Manager already set one.
- **Certifications:** type, number, issued, expiry. An assignment warning appears when an item requires a certification the assignee lacks or has expired [LAB-005].

---

## 15. REPAIR TICKETS [TKT-*]

### 15.1 Fields
number, target (asset, or zone/system), title, description, priority, symptom (problem code, optional), asset_stopped (bool), photos, issuer, status, loop_count (0–3, +1 extra), assignee, claimed_at, first_response_at, report(s), linked_wo_id, SLA due times, resolution type.

### 15.2 State machine [TKT-005, TKT-006]
| From | Event | To | Who |
|---|---|---|---|
| — | create | OPEN (in pool) | O / M (blocked if tenant OVERDUE) |
| OPEN | claim / assign | IN_PROGRESS | Mt / M |
| OPEN | cancel (reason) | CANCELLED | issuer / M |
| IN_PROGRESS | convert to WO | IN_PROGRESS (linked_wo set) | Mt / M |
| IN_PROGRESS | submit report | REPORT_SUBMITTED | assignee (or system when linked WO completes) |
| REPORT_SUBMITTED | accept | CLOSED (resolution: ACCEPTED) | issuer (or M on behalf, §15.5) |
| REPORT_SUBMITTED | feedback (reason), loop_count < 3 | IN_PROGRESS, loop_count + 1 | issuer |
| REPORT_SUBMITTED | feedback, loop_count = 3 | ESCALATED_TO_MANAGER | issuer |
| ESCALATED_TO_MANAGER | force close | CLOSED (resolution: FORCE_CLOSED) | M |
| ESCALATED_TO_MANAGER | require new ticket | CLOSED (resolution: SUPERSEDED), new ticket pre‑filled and linked | M |
| ESCALATED_TO_MANAGER | mandate additional action | IN_PROGRESS (one extra loop; its failure returns to ESCALATED) | M |

### 15.3 Report content [TKT-008]
Work done (text), failure codes (problem/cause/action), labour entries, parts issued, downtime (auto from asset state), photos.

### 15.4 Conversion to WO [TKT-007]
- Creates a CORRECTIVE (or EMERGENCY if priority CRITICAL) WO, pre‑filled with target, description, photos, priority, and an optional template.
- Ticket assignee = WO lead.
- When the WO reaches COMPLETED, the system submits the ticket report from the WO completion data.
- Issuer feedback returns the ticket to IN_PROGRESS. The assignee may reopen the WO (if not CLOSED) or create a follow‑up WO. The loop count applies to the ticket.
- Conversion is **optional**. Simple fixes are reported directly on the ticket.

### 15.5 Issuer inactivity
- If the issuer hasn't reviewed within 2 working days: reminder.
- After 5 working days: the Manager is notified and may accept or return on the issuer's behalf (recorded as "on behalf").

### 15.6 SLA [TKT-009]
Per org unit and priority. The clock is 24/7 or working‑time (§3.7).

| Priority | Response (to claim/assign) | Resolution (to REPORT_SUBMITTED accepted) | Clock |
|---|---|---|---|
| CRITICAL | 1 h | 8 h | 24/7 |
| HIGH | 4 h | 24 h | 24/7 |
| MEDIUM | 1 working day | 5 working days | working |
| LOW | 3 working days | 15 working days | working |

- Time in REPORT_SUBMITTED awaiting the issuer is **excluded** from resolution time.
- A breach sets a flag and notifies the assignee, the Manager, and the issuer (resolution breach only).

### 15.7 Stopped asset [TKT-010]
`asset_stopped = true` creates a MANUAL_STOP cause (§11.1) with an unplanned downtime event, linked to the ticket.

---

## 16. FAILURE CODES & DOWNTIME [REL-*]

- **Failure codes:** three linked lists: Problem (e.g. "Leak", "Vibration"), Cause (e.g. "Seal wear"), Action (e.g. "Replace seal").
  - Each code: code, name (fa/en), active, applicable asset classes (optional).
  - Causes may be restricted to problems.
  - The default catalogue is imported at tenant creation (fa/en).
- **Downtime event:** asset, start, end (null = ongoing), type PLANNED/UNPLANNED, reason (list), source (SAFETY_CAUSE, TICKET, MANUAL, WO), linked WO/ticket, notes.
  - Manual edits by M/O/Mt are audited.
  - Overlapping events on the same asset are merged for KPI purposes.

---

## 17. INVENTORY [INV-*]

### 17.1 Part fields [INV-001]
| Field | Mandatory | Notes |
|---|---|---|
| part_no (SKU) | ✔ | unique per org unit |
| name (fa/en), description | ✔ name | |
| category | ✔ | tenant taxonomy |
| stock_uom | ✔ | |
| purchase_uom + conversion | | |
| manufacturer, manufacturer_part_no | | |
| stocked | ✔ | if false: only direct purchase |
| tracking | ✔ | NONE, LOT, SERIAL |
| shelf_life_days | | lots get expiry |
| criticality | ✔ | A/B/C (default C) |
| alternates | | list of part IDs (one‑way or two‑way) |
| barcode | | defaults to part_no |
| default vendors | | via vendor catalogue |
| image, documents | | |
| rotable | | SERIAL tracking required |
| status | ✔ | ACTIVE, OBSOLETE (no new purchases; issue allowed) |

### 17.2 Storerooms & bins [INV-003]
- **Storeroom:** code, name, org unit, zone (location), type (MAIN, SATELLITE, WORKSHOP, VAN), `self_issue_allowed` (Maintenance can issue), `allow_negative` (default false), keeper(s).
- **Bin:** code, storeroom, description. Default bin `DEFAULT` is auto‑created.

### 17.3 Stock balance [INV-004]
- Key: (part, storeroom, bin, lot/serial). Fields: on_hand, reserved (storeroom level), updated_at.
- Available (per part, storeroom) = Σ on_hand − reserved.
- On order = Σ open PO line quantities (in stock UoM) not yet received, for that storeroom.
- Balances are a **projection** of the ledger, updated in the same transaction as the ledger row.

### 17.4 Ledger transactions [INV-005]
| Type | Qty sign | Cost basis | Effects |
|---|---|---|---|
| OPENING_BALANCE | + | entered unit cost | sets average cost if first |
| RECEIPT | + | PO net unit price (converted to stock UoM) | recalculates average; reduces on order |
| ISSUE | − | current average | charges WO/ticket; releases matching reservation |
| RETURN | + | the original issue's unit cost | credits WO/ticket |
| TRANSFER_OUT / TRANSFER_IN | − / + | current average | paired, same transaction |
| ADJUSTMENT | ± | current average (or entered cost for +) | reason code mandatory (DAMAGE, LOSS, FOUND, DATA_CORRECTION, OTHER) |
| COUNT_ADJUSTMENT | ± | current average | from approved count |
| SCRAP | − | current average | reason |
| RETURN_TO_VENDOR | − | original receipt cost | reduces received qty on PO line |

Every row stores: part, storeroom, bin, lot/serial, qty (stock UoM), unit_cost, value, running on_hand after posting, reference (WO, ticket, PO, receipt, count, adjustment), user, timestamp, reason, reversal_of.

**Corrections** are made by posting a reversing transaction, never by editing.

### 17.5 Costing [INV-011]
Moving weighted average per (part, org unit):
```
new_avg = (on_hand_total × old_avg + receipt_qty × receipt_unit_cost) / (on_hand_total + receipt_qty)
```
- If on_hand_total ≤ 0 before the receipt, new_avg = receipt_unit_cost.
- Tax is excluded from cost if the org unit setting `tax_recoverable = true` (default).

### 17.6 Reservations [INV-006]
- Created when a WO is generated/created with planned parts: `(wo, part, storeroom, qty)`. The default storeroom is the one nearest the asset: same zone, else the org unit's MAIN.
- If available < requested, the reservation is created for the available quantity. The WO shows "shortage" and offers to create a requisition.
- Released by: issue (by issued quantity), WO cancellation, WO closure (remaining), or manual release.

### 17.7 Issue & return [INV-007]
- Issue to WO/ticket by the Storekeeper, or by Maintenance at `self_issue_allowed` storerooms. Scanning the part/bin barcode is supported.
- Requires the WO in state ACKNOWLEDGED/IN_PROGRESS/ON_HOLD/COMPLETED (not CLOSED).
- Tracked parts require a lot/serial. FEFO (first‑expiry, first‑out) lot is suggested.
- Returns only up to the net issued quantity for that WO/part/lot.

### 17.8 Negative stock [INV-008]
- If `allow_negative = false`, an issue/transfer/adjustment making on_hand < 0 at (part, storeroom, bin, lot) is rejected with `INSUFFICIENT_STOCK`.
- Concurrency: postings lock the balance rows (§ architecture).

### 17.9 Reorder [INV-009, INV-010]
- Policy per (part, storeroom): min, max, reorder_point, reorder_qty, lead_time_days, safety_stock. Method MIN_MAX (order up to max) or FIXED_QTY.
- Low‑stock condition: available + on_order ≤ reorder_point. Evaluated on every posting and nightly. It creates a single active alert per (part, storeroom) until resolved.
- Suggested quantity:
  - MIN_MAX: max − (available + on_order).
  - FIXED_QTY: reorder_qty × ⌈(reorder_point − (available + on_order)) / reorder_qty + 1⌉.
  - Rounded up to purchase UoM multiples.
- The reorder suggestion list can be converted (with selection) into a PR or, per vendor, into draft POs.

### 17.10 Serial, lot & rotables [INV-012, INV-013]
- LOT: lot no., expiry (from shelf life or entered). Expired lots cannot be issued without a warning override.
- SERIAL: each unit has a serial record with status: IN_STOCK, ISSUED, INSTALLED, IN_REPAIR, SCRAPPED. Quantity per serial is always 1.
- **Rotable install:** issuing a rotable serial to a WO with "install" creates or links a component asset (serial, part → asset class mapping) under the WO's target asset.
- **Rotable removal:** returns the unit to stock as bin `REPAIR` (status IN_REPAIR, value unchanged), or scraps it. Repair completion moves it back to a normal bin.

### 17.11 Cycle counts [INV-014]
- Count sheet: storeroom, selection (bins, categories, ABC class, or random N), blind (quantities hidden, default) or not.
- States: DRAFT → IN_PROGRESS (snapshot of expected qty taken) → SUBMITTED → APPROVED (COUNT_ADJUSTMENT posted per variance) | RECOUNT.
- Movements during the count: expected qty is adjusted by postings after the snapshot.
- Approval: Storekeeper if |variance value| ≤ threshold (per org unit), else Manager.

### 17.12 Direct / non‑stock purchases [INV-018]
PO lines with destination = WO: on receipt, the cost is charged to the WO (external/parts cost). There is no stock ledger entry except a memo row for traceability. The WO assignee is notified.

---

## 18. PURCHASING [PUR-*]

### 18.1 Vendors [PUR-001]
- Fields: code, name (fa/en), contacts, address, tax/national ID, payment terms, currency (= tenant currency in MVP), default lead time, status (ACTIVE, BLOCKED), rating 1–5, attachments.
- **Vendor catalogue:** (vendor, part, vendor_part_no, price, purchase UoM, min order qty, lead time, preferred flag).

### 18.2 Requisition [PUR-002]
- Lines: part or free‑text item/service, qty, UoM, required date, destination (storeroom or WO), suggested vendor, estimated price.
- States: DRAFT → SUBMITTED → APPROVED | REJECTED (reason) → CONVERTED (all lines on POs) | CANCELLED.
- Partially converted PRs show per‑line status.

### 18.3 Purchase order [PUR-003..006]
- Header: number, vendor, org unit, order date, expected date, delivery storeroom (default), payment terms, notes, discount %, tax %.
- Lines: part/free text, vendor part no., qty (purchase UoM), unit price, line discount, destination (storeroom/bin or WO), required date, source PR line.
- Totals: subtotal, discount, tax, total.
- **State machine:**

| From | Event | To | Who |
|---|---|---|---|
| — | create | DRAFT | S / M |
| DRAFT | submit | PENDING_APPROVAL | S / M |
| PENDING_APPROVAL | approve | APPROVED | M within threshold (else a root‑org M) |
| PENDING_APPROVAL | reject (reason) | DRAFT | M |
| APPROVED | send (PDF download / email) | SENT | S / M |
| SENT / PARTIALLY_RECEIVED | receipt | PARTIALLY_RECEIVED / RECEIVED | S / M |
| PARTIALLY_RECEIVED | close short (reason) | CLOSED | S / M |
| RECEIVED | close | CLOSED (auto after 7 days) | system / S / M |
| DRAFT / PENDING / APPROVED / SENT (nothing received) | cancel (reason) | CANCELLED | M |

- **Approval thresholds** [PUR-004]: per org unit `po_approval_limit`. Above it, approval is by a Manager of the parent/root org unit. Approving requires that the approver did not create the PO (segregation of duties; can be disabled for single‑person tenants).
- Editing an APPROVED/SENT PO (price/qty) returns it to PENDING_APPROVAL, unless the change reduces the total.

### 18.4 Receipt [PUR-007, PUR-008]
- Receipt document: number, PO, date, received_by, delivery note no., lines (PO line, qty received, bin, lot/serial, expiry), attachments.
- Rules:
  - Received cumulative qty ≤ ordered × (1 + over_receipt_tolerance), with tolerance default 0%.
  - Posts RECEIPT ledger rows (stock lines) or a WO charge (direct lines).
  - Updates PO state.
  - Releases WOs ON_HOLD with reason WAITING_FOR_PARTS where that WO's shortages are now covered (the system notifies the assignee and offers resume).
- A receipt can be reversed (Manager) by posting reversing rows, if the stock is still available.

### 18.5 Return to vendor [PUR-009]
References a receipt line. Posts RETURN_TO_VENDOR, reduces the received qty, and may reopen the PO line for replacement delivery (option).

---

## 19. NOTIFICATIONS & ANNOUNCEMENTS [NOT-*]

### 19.1 Notification record
tenant, org unit, user, category, severity (INFO, WARNING, CRITICAL), title key + params (rendered in the user's language at display time), entity type/id, deep link, read_at, created_at, expires_at (= created + 30 d).

### 19.2 Event catalogue [NOT-005]
| Event | Recipients | Severity | Mutable |
|---|---|---|---|
| WO assigned / reassigned | assignees / team | INFO | ✔ |
| WO due soon (at due − 24 h, or start of the due day) | assignees | INFO | ✔ |
| WO overdue | assignees, Manager | WARNING | ✔ (Manager copy) |
| WO snooze expired | assignee | INFO | ✗ |
| WO rejected | Managers of org unit | WARNING | ✗ |
| WO returned by QC | assignees | WARNING | ✗ |
| Cycle skipped (open WO) / cycle error | Managers | WARNING | ✔ |
| Safety stop activated / deadline critical stop | Managers, assignees, users with the asset's zone in scope and role O | CRITICAL | ✗ |
| Ticket new in pool | Maintenance in scope | INFO | ✔ |
| Ticket claimed / assigned | issuer, assignee | INFO | ✔ |
| Ticket report submitted | issuer | INFO | ✗ |
| Ticket feedback returned | assignee | WARNING | ✗ |
| Ticket escalated | Managers | WARNING | ✗ |
| Ticket SLA breach | assignee, Managers (+ issuer for resolution) | WARNING | ✗ |
| Low stock | Storekeepers, Managers | WARNING | ✔ |
| PR submitted / PO awaiting approval | approvers | INFO | ✗ |
| PR/PO approved / rejected | creator | INFO | ✔ |
| Parts received for WO | WO assignees | INFO | ✔ |
| Import/export/clone/report finished or failed | requester | INFO/WARNING | ✗ |
| AI job finished/failed; manual ingestion finished/failed | requester / uploader | INFO | ✔ |
| MCP action awaiting confirmation | users permitted for the action | WARNING | ✗ |
| Announcement posted | target audience | INFO / CRITICAL | ✗ |
| Invitation accepted | inviter | INFO | ✔ |
| Certification expiring (30 d) | user, Managers | INFO | ✔ |

### 19.3 Delivery
- In‑app via polling (30 s when visible) and server‑sent events (optional).
- Web push if opted in [NOT-003]. CRITICAL events always push to subscribed devices.

### 19.4 Announcements [NOT-006]
Fields: title, body (fa/en), audience (org unit, include sub‑orgs, roles), severity, publish_at, expires_at, requires_ack. Acknowledgement is tracked per user, with a report of who has not acknowledged.

---

## 20. REPORTING & KPIs [RPT-*]

All KPIs are filterable by period, org unit (with/without sub‑orgs), zone, system, asset class, criticality, work type, and priority.

| KPI | Definition |
|---|---|
| PM compliance % | PM/inspection WOs with a due date in the period completed on or before deadline ÷ PM/inspection WOs with a due date in the period (+ MISSED evaluations). Cancelled by Manager excluded. |
| Planned vs unplanned % | hours (labour) or count of PREVENTIVE+INSPECTION+PREDICTIVE vs CORRECTIVE+EMERGENCY WOs completed in the period |
| Backlog | open WOs (count) and Σ estimated remaining hours; backlog weeks = backlog hours ÷ weekly available craft hours |
| WO ageing | open WOs bucketed by age since issue (0–7, 8–30, 31–90, > 90 d) |
| Overdue WOs | count where the overdue flag is set |
| MTTR | Σ duration of unplanned downtime events closed in the period ÷ number of those events |
| MTBF | (period operating time − Σ unplanned downtime) ÷ number of unplanned failures (unplanned downtime events or CORRECTIVE/EMERGENCY WOs with a problem code) in the period |
| Availability % | (period time − Σ downtime of any type) ÷ period time. Period time uses the calendar or the asset's operating schedule (24/7 default). |
| Ticket SLA compliance % | tickets closed in the period without response/resolution breach ÷ tickets closed |
| Maintenance cost | Σ labour + parts + external from WOs/tickets completed in the period, grouped |
| Inventory value | Σ on_hand × average cost at the end of the period |
| Stock‑outs | count of issue attempts refused for insufficient stock + days with available ≤ 0 for stocked parts with reorder policy |
| Inventory turnover | issue value in 12 months ÷ average inventory value |
| Slow‑moving / dead stock | parts with no ISSUE in 180 / 365 days and on_hand > 0 |
| Safety incidents | count of DEADLINE_STOP causes and Manager overrides of safety causes |

- **Scheduled reports** [RPT-006]: a report definition (type, filters, language, calendar), a recurrence (§10.3 rule), and recipients (org members only). The PDF is generated in the background, stored 7 days, emailed as an attachment (≤ 10 MB; otherwise a link), and posted to the notification centre.
- **Exports** [RPT-005]: CSV (UTF‑8 with BOM for Excel compatibility with Persian) and XLSX. Large exports run as background jobs.

---

## 21. SEARCH, COMMENTS, TIMELINE [COL-*]

- **Global search** [COL-001]:
  - Prefix/trigram search across the entity list in requirements, normalized per §5.2.
  - Results are grouped by type, top 5 per type, with a "see all" link.
  - Permission and zone scope filters are applied **before** ranking.
  - Exact code/number matches are ranked first.
- **Manual content search** [COL-002]: hybrid keyword + vector search across ingested manual chunks the user may access. Hits show document, page, and snippet.
- **Saved views** [COL-003]: per user, named filter/sort/column sets. Managers may share a view with the org unit.
- **Comments** [COL-004]:
  - Markdown‑lite (bold, lists, links), max 5,000 chars, images ≤ 5 per comment.
  - @mention of users with access to the entity notifies them.
  - Editable by the author for 15 min, then immutable. Deletion is shown as "comment removed".
- **Asset timeline** [AST-013]: event stream types: WO_CREATED/COMPLETED, TICKET_*, READING, BASELINE_RESET, PART_ISSUED/RETURNED, MOVED, INSTALLED/REMOVED, DOWNTIME, FAILURE_CODED, STATE_CHANGED, AI_SUGGESTION_USED, DOCUMENT_ADDED. Filterable, with "include components".

---

## 22. FILES & DOCUMENTS [FILE-*]

- Validation: extension allow‑list + MIME + magic bytes. Max size by purpose (attachments 10 MB, manuals 50 MB, import files 20 MB), configurable per tier.
- HEIC is converted to JPEG. Images get a thumbnail (320 px) and a preview (1280 px). EXIF GPS data is stripped unless the org setting keeps it.
- Antivirus: files are quarantined (not downloadable) until the scan passes [SEC-005].
- **Documents** (typed files) can be linked to many entities: `document_links(document_id, entity_type, entity_id)`. Deleting a link doesn't delete the document. Deleting a document requires no remaining links, or confirmation.
- Manual ingestion status: PENDING, PROCESSING, COMPLETED, FAILED (reason). Reprocess is available to Managers.
- Storage quota per tier. An upload exceeding the quota is refused with `STORAGE_QUOTA_EXCEEDED`.

---

## 23. IMPORT / EXPORT [IMP-*]

- **Templates:** an XLSX file per entity with a header row in the user's language, a hidden machine header row, dropdown validation lists, and an example row.
- **References** between rows use codes (e.g. `parent_asset_code`, `zone_code`). Within one file, a row may reference another row of the same file (e.g. parent asset). Ordering is resolved automatically.
- **Process** [IMP-002]:
  1. Upload.
  2. Parse & validate (types, mandatory fields, references, uniqueness, tier limits).
  3. Preview: counts of create/update/error, plus row errors with column and message.
  4. Commit: all‑or‑nothing, background job.
  5. Result report downloadable.
- **Mode:** CREATE_ONLY or UPSERT (matched by code).
- Opening stock import posts OPENING_BALANCE transactions and is allowed only for parts/storerooms with no prior transactions.
- User import creates invitations (not accounts).
- Dates are accepted in Jalali or Gregorian (column setting). Digits are normalized.

---

## 24. ONBOARDING [IMP-004, IMP-005]

- At org creation, the Owner picks a starter template (or blank) and a language. The template content is created in the chosen language (both languages where available).
- **Wizard steps:**
  1. Org profile & calendar.
  2. Zones (rename/add).
  3. Review systems & asset classes.
  4. Assets (edit sample list or import).
  5. Review cycles (activate/suspend).
  6. Invite team.
  7. Done.
- Sample data carries an `is_sample` flag, and a one‑click "remove all sample data" is available until the first real WO is completed.
- Tooltips are shown once per user per screen, and can be reset in the profile.

---

## 25. AI COPILOT [AI-*]

### 25.1 AI draft lifecycle
AI outputs are stored as **AI drafts**:
- id, feature, input, context refs, raw output, parsed output, confidence, rationale, model/provider/version, fallback flag, status.
- States: GENERATING → READY → (UNDER_REVIEW with Reporter/Maintenance suggestions) → APPROVED | REJECTED (reason) | EXPIRED (30 days unused).
- Approval materializes the result:
  - template DRAFT version → published by the Manager;
  - approved repair plan attached to ticket/WO;
  - accepted auto‑fill values written to the form.
- Nothing is applied from READY without an explicit user action [AI-001].

### 25.2 Features
| Feature | Trigger | Context used | Output schema | Approver |
|---|---|---|---|---|
| Checklist generation [AI-002] | "AI Generate" in template editor; prompt in fa/en | asset class, optional asset specs, tenant's similar templates (same class), manual chunks for the class | items: description, measurement (type, unit, min, max), est. duration, risk, tools, skills, safety flag suggestion | Manager |
| Workflow generation [AI-003] | same | same | graph: tasks + AND splits + DECISIONs with conditions in §12.3 grammar | Manager (validation must pass) |
| Manual assistant [AI-004] | chat panel on asset/WO/ticket | manual chunks linked to asset + asset class (only those the user can access) | answer + citations (document, page) | n/a (informational) |
| Troubleshooting [AI-005] | ticket creation (async), "Suggest" on corrective WOs | symptom, asset class, asset history (last 24 months), failure‑code statistics for the class within the tenant, manual chunks | ranked causes (with failure code mapping) + steps + parts + safety notes | Maintenance / Manager |
| Auto‑fill [AI-006] | WO/ticket form, "Suggest" | k = 10 most similar completed WOs (vector + structured similarity) | description, planned parts, duration, crafts, failure codes | form user |

### 25.3 Confidence [AI-007]
Confidence expresses **evidence support**, not guaranteed correctness. Score 0–100, bands: High ≥ 75, Medium 40–74, Low < 40 (Low shows a warning banner).

| Feature | Formula |
|---|---|
| Manual assistant | `100 × (0.6 × mean_sim(cited chunks) + 0.4 × cited_sentence_ratio)`, where similarity is normalized to [0,1] against the calibrated threshold and `cited_sentence_ratio` = answer sentences carrying a valid citation ÷ all sentences. No chunk above threshold → no answer ("not found"), score 0. |
| Troubleshooting (per cause) | `min(100, 60 × (1 − e^(−n/3)) + 40 × m)`, where n = similar historical failures on the class with that cause, m = 1 if a manual citation supports it, else 0 |
| Auto‑fill (per field) | `100 × share × mean_similarity`, where share = fraction of the k neighbours agreeing on the value (numeric: within ±20% of the median) |
| Template generation | `100 × (0.5 × evidence + 0.5 × validity)`, where evidence = min(1, (similar templates + cited chunks) / 5) and validity = 1 if the first output passed schema + graph validation, 0.5 if it passed after one repair |

The rationale is generated from the same inputs (e.g. "4 similar failures on Centrifugal Pump; Manual 'KSB Etanorm' p.42").

### 25.4 Fallback [AI-011]
When the provider is unavailable (timeout 60 s, 3 retries with backoff) or quota is exhausted:
- **Manual assistant:** return the top 3 chunks as passages with citations, labelled "Fallback – no AI summary".
- **Template generation:** propose the most similar existing tenant template (by class and text), copied as a draft and labelled "Fallback – based on existing template X". If none exists, show an error.
- **Troubleshooting / auto‑fill:** show the statistics‑only result (most frequent causes/values from neighbours) without generated text.

`fallback_used = true` is logged.

### 25.5 Privacy [AI-012]
- **Sanitizer for external providers:**
  - Removes tenant/org/user names and IDs, addresses, phone numbers, emails, zone names.
  - Replaces asset codes/serials with neutral placeholders (`<ASSET_1>`), restored in the response.
  - Keeps asset class, manufacturer/model (configurable: can also be masked), measurements, and maintenance text.
- **Privacy mode (tenant):** only self‑hosted models may be used. If none is configured, AI features are disabled with an explanation.
- In‑app assistant answers never trigger write actions [SEC-008].

### 25.6 Quotas [AI-013]
- Per tenant, monthly: tokens and requests per tier. Per user: 30 requests/min.
- At 80% of quota the Managers are notified. At 100%, fallback mode applies until the next month or an upgrade.

---

## 26. AI TRAINING DATA [AIT-*]

### 26.1 Interaction record [AIT-001]
`id, tenant_id, org_unit_id, user_id, feature, created_at, model, provider, model_version, prompt_version, input (sanitized + original), context_refs, raw_output, final_output (human‑approved/edited), decision (APPROVED | EDITED | REJECTED | IGNORED), rejection_reason, edit_distance, confidence, fallback_used, manager_label (GOOD | BAD | EXCLUDE), consent_snapshot`

### 26.2 Per‑tenant dataset [AIT-002]
- Consists of all records of the tenant not labelled EXCLUDE.
- Used only for models/adapters bound to that tenant (`model_scope = tenant_id`).
- The export requires the tenant's contractual permission flag (set by SYS_ADMIN from the contract) and is audited.

### 26.3 Broad dataset pipeline [AIT-003, AIT-007, AIT-008]
A record is eligible if:
- the tenant's consent is ON at record creation,
- the feature is in the allowed list, and
- the decision is APPROVED/EDITED (REJECTED records are included only as negative examples, with their reason).

Pipeline (batch, weekly):
1. **Dictionary redaction:** remove every term in the tenant dictionary (tenant/org‑unit names, zone names, asset names/codes/serials, user names, vendor names, part numbers, custom field values) → typed placeholders.
2. **Pattern redaction:** emails, phone numbers (incl. Iranian `09xxxxxxxxx`, `+98`), national IDs (10 digits), IBAN (`IRxx…`), URLs, IPs, postal codes, coordinates, alphanumeric serial‑like tokens → placeholders.
3. **NER redaction (fa + en):** person, organization, and location names.
4. **Generalization:** dates → removed or relative; numeric values kept only in measurement context; manufacturer/model kept only if the model is used by ≥ 5 tenants on the platform (else → `<MODEL>`).
5. **Stripping:** no tenant/org/user/record IDs. Records are shuffled and batch‑dated only (month).
6. **Quality gate:** automated PII scan on the output. If any hit, the record is dropped. A 1% random sample per batch is human‑reviewed. A batch fails if residual PII > 0.1%.

Output: a separate storage bucket and a separate DB schema, with **no foreign keys or hashes** linking back to the source [AIT-007].

### 26.4 Consent [AIT-004]
- The setting is changeable only by the Owner, with a timestamped history.
- Turning consent OFF excludes future records and records not yet processed. Already anonymized records remain (disclosed).

---

## 27. MCP [MCP-*]

### 27.1 API keys [MCP-003]
- Fields: name, org unit, role, zone scope, read_only, expires_at (max 1 year), created_by, last_used_at, status (ACTIVE, REVOKED, EXPIRED).
- The secret is shown once and stored hashed. Rotation creates a new secret and keeps the old one valid for 24 h.
- A key's effective permissions = its role's permissions ∩ (read‑only if flagged) ∩ tier (Free: read‑only).

### 27.2 Resources, tools, prompts [MCP-001]
- **Resources (read):**
  - `cmms://org-units`
  - `cmms://zones`
  - `cmms://systems`
  - `cmms://assets/{id}` (+ `/components`, `/history`, `/meters`, `/documents`, `/bom`)
  - `cmms://cycles/{id}`
  - `cmms://templates/{id}`
  - `cmms://work-orders`, `cmms://work-orders/{id}`
  - `cmms://tickets`, `cmms://tickets/{id}`
  - `cmms://parts/{id}` (+ `/stock`)
  - `cmms://storerooms`
  - `cmms://purchase-orders/{id}`
  - `cmms://reports/kpis`
  - `cmms://notifications`
- **Tools:** one tool per domain command available to the key's role, grouped as:
  - Assets: `create_asset`, `update_asset`, `move_asset`, `decommission_asset`*, `clone_zone`*
  - Meters: `log_reading`, `reset_baseline`
  - Cycles: `create_cycle`, `update_cycle`, `suspend_cycle`, `activate_cycle`, `launch_cycle`
  - Templates: `create_template_draft`, `ai_generate_template` (never publish)
  - WOs: `create_work_order`, `acknowledge`, `update_item`, `record_measurement`, `add_labour`, `add_comment`, `snooze`, `reject`, `hold`, `complete_work_order`
  - Tickets: `create_ticket` (CRITICAL*), `claim_ticket`, `submit_ticket_report`, `convert_ticket_to_wo`
  - Safety: `set_safety_flag` (STOP_UNTIL_COMPLETE*)
  - Inventory: `issue_part`, `return_part`, `transfer_stock`, `adjust_stock` (above threshold*), `create_requisition`
  - Purchasing: `create_po_draft`, `submit_po`, `approve_po`*, `receive_po`
  - AI: `ask_manual_assistant`, `suggest_troubleshooting`
  - Reports: `get_kpis`, `export_report`
  - `undo_last_operations`

  (* = confirmation gate, §27.3; bulk operations > 10 records are also gated.)
- **Prompts:** `cycle-analysis`, `overdue-triage`, `root-cause`, `zone-onboarding`, `reorder-review`.

### 27.3 Confirmation gate [MCP-005]
- The gated tool returns `status: PENDING_CONFIRMATION` with a `pending_action_id` and a UI link.
- A pending action shows: key name, tool, human‑readable diff/effect preview (dry‑run result), and expires_at (24 h).
- Approve/reject is done by a user holding the required permission. On approval the action executes with the approver recorded as the confirming actor.

### 27.4 Dry run, limits, undo [MCP-006, MCP-007, MCP-009]
- `dry_run: true` returns validation results and the computed effects, without persisting anything.
- Rate limits:
  - Default per key: 60 read calls/min, 30 write calls/min, 10 AI calls/min.
  - Tier multipliers apply.
  - Ceilings: 50 WOs and 50 tickets per key per hour.
- **Undo:** each write records a compensating command. `undo_last_operations(n)` executes the compensations in reverse order, for operations ≤ 5 min old, when no later human change touched the same records. Otherwise the undo is refused, listing the conflicts.
- Non‑compensable operations (e.g. approved PO sent, stock issued then consumed by a closed WO) are marked as such in the tool description.

---

## 28. MOBILE, QR & OFFLINE [MOB-*]

- **QR scan page** [MOB-003]:
  - Asset card: name, code, zone/position, operating state with active causes, safety badges, warranty badge.
  - Tabs: open work (WOs/tickets), history, documents, meters, components.
  - Quick actions per role: Create ticket, Log reading, Start my WO, Ask manual.
- **Quick actions** [MOB-004]: min 48 px touch targets; the bottom action bar is mirrored for RTL.
- **Offline** [MOB-005]:
  - Cached: assigned open WOs (snapshot + items), their assets' cards, and manuals opened in the last 7 days (≤ 200 MB).
  - Allowed offline:
    - item status/results/measurements
    - comments
    - photos (queued)
    - meter readings
    - labour timer entries
  - Each queued command carries a client UUID (idempotency key) and a client timestamp.
  - **Sync:** commands are sent in order. The server validates each against the current state.
    - Conflicts: WO no longer executable, item already completed by someone else, reading below the latest.
    - Conflicting commands are rejected and shown to the user in a "Sync issues" list with the server value. Nothing is silently overwritten.
  - Offline indicator and count of pending changes are always visible.

---

## 29. AUDIT CATALOGUE [AUD-*]

| Domain | Audited actions |
|---|---|
| Auth | login success/failure, logout, password reset, email change, session revoke, lockout |
| Tenancy | org unit create/update/archive/restore, subscription/tier/payment state change, ownership transfer, AI consent change |
| Membership | invite create/revoke/accept/expire, role/scope change, deactivate/reactivate |
| Assets | create, update (field diff), move, install/remove, lifecycle change, delete/restore, clone |
| Meters | reading void/correction, replacement, rollover, baseline reset |
| Cycles | create/update/suspend/activate/archive, manual launch, override on instance |
| Templates | version create/publish/retire |
| WOs | every status transition, assignment change, deadline/priority change, QC decision, signature, safety override |
| Tickets | every status transition, assignment, escalation decision, on‑behalf review |
| Safety | cause created/cleared/overridden |
| Inventory | every ledger posting (reference), reorder policy change, count approval |
| Purchasing | PR/PO state transitions, approvals, receipt/reversal, vendor block |
| AI | draft approval/rejection, template generated, training log label changes, dataset exports |
| MCP | every tool call (actor MCP_AGENT, key id, tool, input hash, result), key create/rotate/revoke, confirmation decisions, undo |
| Platform | SYS_ADMIN support sessions (start, reason, end, accessed entities), tenant export/purge |
| Data | imports (commit), exports (full and list) |

The audit log is append‑only (DB permissions + trigger preventing UPDATE/DELETE). Each row carries a hash chain value (`prev_hash`) for tamper evidence.

---

## 30. VALIDATION & ERROR CONVENTIONS

- **Error response:** `{ "error_code": "INSUFFICIENT_STOCK", "message": "<localized>", "params": {...}, "details": [ { "field": "...", "code": "...", "params": {...} } ], "request_id": "..." }`.
- The client renders messages from `error_code` + `params` using its i18n catalogue. The `message` field is a server‑rendered fallback in the user's language.
- Examples of required human‑readable messages:
  - "Cannot decommission – 3 open work orders" (`HAS_OPEN_WORK`)
  - "Tier limit reached: 100 of 100 assets" (`TIER_LIMIT_REACHED`)
  - "Only 2 pcs available in Main Store" (`INSUFFICIENT_STOCK`)
  - "Reading is lower than the last reading (1,250 h on 1405/07/02)" (`METER_NOT_MONOTONIC`)
  - "Repair tickets are disabled while the subscription is overdue" (`TENANT_OVERDUE`)
- **Background task status centre** [NOT-007]: every async job exposes `{id, type, status: PENDING | RUNNING | SUCCEEDED | FAILED, progress 0–100, result_link, error}` to its requester for 7 days.
