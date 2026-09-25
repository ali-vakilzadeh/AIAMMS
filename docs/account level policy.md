# AIAMMS – ACCOUNT LEVEL POLICY

| Item | Value |
|---|---|
| Document version | 1.0 |
| Date | 2026‑09‑25 |
| Status | Approved (levels, entitlement table, per‑asset prices). Items in §11 are proposed defaults to confirm. |
| Implemented by | Account Management Service (AMS) — `account_management_service.md` |
| Referenced by | `requirements.md` COM‑003 … COM‑016 |

This document is the single source for account levels, prices, and what each level includes. The CMMS never reads this document directly. The AMS turns it into **entitlements** (limits and features), and the CMMS enforces them.

---

## 1. PRINCIPLES

1. **Charge per asset, not per user.** Assets measure the customer's size and the value they get. Users are unlimited on every paid level, so customers never ration logins, and more users give the AI more data.
2. **Requesters are always free.** Operators who only scan QR codes and raise tickets are unlimited on every level, including Free.
3. **Gate what costs money or needs scale, not code.** The code is AGPL and self‑hosters get every feature. SaaS levels differ by hosting capacity, AI usage, storage, SMS, multi‑site scale, support, and SLA.
4. **AI is sold as credits, not tokens** (§6).
5. **Free covers the whole core workflow:** assets → PM cycle → work order → QR → ticket → mobile.
6. **Four levels, Premium is the recommended level.** New tenants start with a Premium reverse trial (§7).

---

## 2. LEVELS

| | **Free** | **Pro** | **Premium** ★ | **Enterprise** |
|---|---|---|---|---|
| AMS plan code | `FREE` | `PRO` | `PREMIUM` | `ENTERPRISE` |
| Target | Workshops, evaluation | Single site, small team | Multi‑site, growing plant | Large industry, groups, regulated sectors |
| Price | 0 | **0.20 USD / asset / month** | **0.25 USD / asset / month** | **Negotiable** (contract) |
| Asset range | up to 100 | 100 – 1,000 | 100 – 10,000 | any (contract) |
| Billing | — | Monthly or annual | Monthly or annual | Annual (contract) |

---

## 3. PRICING (FLAT PER ASSET)

### 3.1 Billable asset
A billable asset is an **active asset** as defined in COM‑004: any asset, including component assets, whose lifecycle status is not DECOMMISSIONED and that is not deleted. Zones, systems, parts, users, and requesters are never billed.

### 3.2 Committed asset quantity
- The Owner chooses a **committed asset quantity** for the billing period.
- This quantity becomes the tenant's asset limit (`assets.active.max`).
- **Monthly price = committed quantity × rate.** There is no per‑user charge and no base fee.

| Level | Rate | Example |
|---|---|---|
| Pro | 0.20 USD / asset / month | 1,000 assets = **200 USD / month** · 250 assets = 50 USD / month |
| Premium | 0.25 USD / asset / month | 1,000 assets = 250 USD / month · 10,000 assets = 2,500 USD / month |
| Enterprise | Negotiated | Per contract (§3.6) |

### 3.3 Annual billing
Annual price = 10 × monthly price (2 months free), paid in advance.

### 3.4 Changing the quantity
- **Increase:** any time. The difference is charged pro rata for the rest of the period, and the new limit applies at once.
- **Decrease:** takes effect at the next renewal. The new quantity cannot be lower than the current active asset count.
- **Reaching the limit:** new assets are refused with `TIER_LIMIT_REACHED` and an upgrade link (COM‑006). There are **no automatic overage charges**.

### 3.5 Changing level
| Change | Rule |
|---|---|
| Free → Pro / Premium | Immediate, after payment. |
| Pro → Premium | Immediate. Remaining Pro credit is applied pro rata. |
| Pro above 1,000 assets | Requires Premium. |
| Premium above 10,000 assets | Requires Enterprise. |
| Downgrade (any) | At next renewal. Existing data stays usable. Over‑limit items follow COM‑006. Features not in the new level become read‑only (e.g. sub‑orgs above the limit keep their data but no new ones can be created). |

### 3.6 Enterprise (negotiable)
The contract sets:
- price per asset or a fixed annual fee;
- asset quantity and volume discounts;
- AI credit pool, storage, SMS volume;
- SLA, support model, data residency, dedicated database;
- AI privacy mode (tenant's own or local LLM);
- payment terms and currency.

### 3.7 Currency and taxes
- **USD is the reference currency** for list prices.
- Local price lists (e.g. IRR) are defined per market in the AMS and may be rounded or adjusted to local purchasing power.
- Prices exclude taxes. VAT or local taxes are added by the AMS according to the account's country.

---

## 4. ACCOUNT LEVEL ASSIGNMENT TABLE

Rows use the entitlement keys of `account_management_service.md` §6. `∞` = unlimited (`null`). "Quantity" = the committed asset quantity (§3.2).

### 4.1 Limits
| Key | Free | Pro | Premium | Enterprise |
|---|---|---|---|---|
| `assets.active.max` | 100 | Quantity (≤ 1,000) | Quantity (≤ 10,000) | Contract |
| `org_units.sub.max` | 0 | 2 | 20 | ∞ |
| `users.max` (full roles) | 5 | ∞ | ∞ | ∞ |
| Requesters (ticket‑only operators) | ∞ | ∞ | ∞ | ∞ |
| `ai.credits.monthly` | 50 | 1,000 | 5,000 | Contract (pooled) |
| `storage.bytes.max` | 2 GB | 50 GB | 250 GB | 1 TB+ (contract) |
| `notify.sms.monthly` | 0 | 0 (add‑on) | 500 | Contract |
| `mcp.calls.monthly` | 1,000 | 20,000 | 200,000 | Contract |
| `audit.retention_days` | 90 | 365 | 1,095 | 2,555 or contract |

### 4.2 Features
| Key | Free | Pro | Premium | Enterprise |
|---|---|---|---|---|
| Assets, PM cycles, WOs, tickets, QR, PWA (core) | ✔ | ✔ | ✔ | ✔ |
| `inventory` | Basic stock only | ✔ | ✔ | ✔ |
| `purchasing` | — | ✔ | ✔ | ✔ |
| `ai.rag` (manual assistant) | ✔ | ✔ | ✔ | ✔ |
| `ai.generation` (checklists / workflows) | ✔ | ✔ | ✔ | ✔ |
| `ai.troubleshoot` | — | ✔ | ✔ | ✔ |
| `ai.autofill` | — | ✔ | ✔ | ✔ |
| `ai.privacy_mode` (tenant's own / local LLM) | — | — | — | ✔ |
| `mcp.read` | ✔ | ✔ | ✔ | ✔ |
| `mcp.write` | — | ✔ | ✔ | ✔ |
| `consolidated_reports` (sub‑org roll‑up) | — | — | ✔ | ✔ |
| `scheduled_reports` | — | ✔ | ✔ | ✔ |
| `exports.xlsx_pdf` (CSV always allowed) | — | ✔ | ✔ | ✔ |
| `audit.export` | — | ✔ | ✔ | ✔ |
| `notify.web_push` | ✔ | ✔ | ✔ | ✔ |
| `notify.email` (operational; auth email always on) | — | ✔ | ✔ | ✔ |
| `notify.sms` | — | Add‑on | ✔ | ✔ |
| `notify.webhook` | — | — | ✔ | ✔ |
| `data_residency` / dedicated DB | — | — | — | Option |

### 4.3 Support and service level
| | Free | Pro | Premium | Enterprise |
|---|---|---|---|---|
| Support | Community | Email, 2 business days | Priority, 1 business day | Dedicated contact, contract |
| Availability SLA | — | — | 99.5% (NFR‑006) | 99.9% or contract |

---

## 5. ADD‑ONS

Sold on top of Pro and Premium and delivered as extra entitlement amounts:

| Add‑on | Unit | Price |
|---|---|---|
| AI credit pack | 1,000 credits / month | TBD after cost modelling (§11) |
| SMS pack | 500 SMS / month | TBD per market |
| Storage | +50 GB | TBD |
| Extra sub‑orgs (Pro) | +1 | TBD |

Asset capacity is not an add‑on. It is bought by raising the committed quantity (§3.4).

---

## 6. AI CREDITS

Customers see credits. The AMS converts them to token budgets internally.

| Action | Credits |
|---|---|
| Manual assistant question (RAG answer) | 1 |
| Troubleshooting suggestion | 3 |
| Checklist / workflow generation | 5 |
| Auto‑fill suggestion | 0.5 |
| Manual ingestion (embedding, self‑hosted) | 0 |

- Credits reset monthly and do not roll over.
- When credits run out, AI requests return `AI_QUOTA_EXCEEDED` with an upgrade/add‑on link. Non‑AI features are unaffected.
- The credit weights and the credit‑to‑token rate are reviewed when real per‑action costs are measured (M5), so margins hold if model prices change.

---

## 7. TRIAL AND FREE LEVEL

- **Reverse trial:** a new tenant starts on **Premium for 30 days**, up to 500 assets, with no payment details.
- At the end of the trial, the tenant moves to **Free** unless the Owner has chosen a paid level. Data above Free limits stays readable (COM‑006).
- Free has no time limit.
- One trial per organization (checked by the AMS).

---

## 8. PAYMENT STATUS

Payment status effects follow COM‑008 and are sent by the AMS as the entitlement `status`:

| Status | Effect |
|---|---|
| CURRENT | Normal use |
| OVERDUE | Everything works except creating new repair tickets |
| SUSPENDED (default 30 days after OVERDUE) | Read‑only, plus payment, data export, and profile |
| CLOSED | Tenant closure rules (ORG‑015) |

---

## 9. SELF‑HOSTED EDITION

- Free of charge under AGPL‑3.0.
- `AMS_MODE=static`: every feature, no limits.
- Paid support contracts for self‑hosters may be offered separately (not part of this policy).

---

## 10. MVP IMPLEMENTATION

- The MVP AMS stub returns **ENTERPRISE with unlimited limits** for every tenant (COM‑013). This policy is not enforced until the AMS policy engine (COM‑015) is built.
- The CMMS enforcement registry must already support every key in §4, so switching the AMS from stub to policy engine needs no CMMS change.

---

## 11. ITEMS TO CONFIRM (PROPOSED DEFAULTS)

| # | Item | Proposed default |
|---|---|---|
| P1 | Minimum committed quantity for Pro and Premium | 100 assets (Pro min 20 USD/month, Premium min 25 USD/month) |
| P2 | Trial asset cap | 500 assets |
| P3 | Annual discount | 2 months free |
| P4 | Add‑on prices | After cost modelling (D8) |
| P5 | Local (IRR) price list | Set per market in the AMS |
| P6 | AI credit weights (§6) | As listed, reviewed in M5 |
