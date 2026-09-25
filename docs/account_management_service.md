# AIAMMS – ACCOUNT MANAGEMENT SERVICE (AMS)
## Design & Messaging Protocol v1

| Item | Value |
|---|---|
| Document version | 1.0 |
| Date | 2026‑09‑25 |
| Status | Protocol: complete (v1). AMS policies: deferred — MVP ships a stub responder. |
| Related | `account level policy.md` (levels, prices, entitlement table), `requirements.md` COM‑*, `project_specification.md` §3.6, `architecture.md` §6.8 |

---

## 1. PURPOSE & BOUNDARY

The AMS is a **separate, fully isolated service** that owns everything commercial. The CMMS server never handles money, prices, invoices, or payment providers. It only consumes **entitlements** ("account credits") and enforces them.

| Concern | Owner |
|---|---|
| Plans, prices, currencies, taxes, invoices, payments | **AMS** |
| Payment providers (different per country), checkout UI, billing portal | **AMS** |
| Account policies (trial rules, dunning, grace, upgrades, discounts, country rules) | **AMS** (deferred) |
| Deciding a tenant's plan, status, limits and features → the **entitlement** | **AMS** |
| Enforcing an entitlement (asset limit, AI quota, MCP write, blocked actions) | **CMMS** |
| Counting usage (assets, users, AI tokens, SMS sent) and reporting it | **CMMS** → AMS |

Design rules:
1. **The CMMS never branches on a plan name.** It enforces only the `limits`, `features`, `status`, and `blocked_actions` of the entitlement. The current plans (`FREE`, `PRO`, `PREMIUM`, `ENTERPRISE`) and their values are defined in `account level policy.md`; new or country‑specific plans need no CMMS change.
2. **The AMS never sees CMMS data.** It knows tenants only by an opaque `tenant_ref`. It receives usage counts, never operational records.
3. **Every message is signed and encrypted**, in both directions, including errors.
4. **The CMMS keeps working when the AMS is down** (§9).
5. **One AMS can serve several CMMS deployments** (e.g. one per country or region), each registered as a client.

---

## 2. DEPLOYMENT MODES

| Mode (`AMS_MODE`) | Where the AMS runs | Used for |
|---|---|---|
| `remote` | Separate container/host reached over HTTPS. May be in the same Compose stack (`http://ams:8200`) or anywhere else. **The protocol is identical in both cases**, so moving the AMS is a configuration change. | SaaS |
| `static` | No AMS. The CMMS uses a built‑in adapter that returns a fixed entitlement from `AMS_STATIC_PLAN` (default `ENTERPRISE`, unlimited). No network, no keys. | Self‑hosted edition [COM‑002], development |

Code layout (monorepo, no imports between `server` and `ams`):
```
protocol/        # shared: JSON Schemas for all messages, JOSE helpers, test vectors
ams/             # the AMS service (Python, FastAPI) — own Dockerfile, own database
server/          # the CMMS; talks to AMS only through protocol/ + the EntitlementPort
```
The JSON Schemas in `protocol/` are the contract. The AMS can be rewritten in another language (e.g. Go) as long as it passes the shared test vectors.

The AMS has **its own PostgreSQL database** (not a schema in the CMMS database), its own backups, and its own secrets.

---

## 3. SECURITY MODEL

### 3.1 Layers
| Layer | Mechanism |
|---|---|
| Transport | HTTPS, TLS 1.3. Optional mutual TLS (`AMS_MTLS_*`). |
| Authenticity & integrity | Every message is a **JWS** signed by the sender (`EdDSA`, Ed25519, RFC 8037). |
| Confidentiality | The signed JWS is wrapped in a **JWE** encrypted to the receiver (`alg: ECDH-ES+A256KW`, `enc: A256GCM`, X25519 keys). **Sign, then encrypt.** |
| Freshness / replay | `iat`, `exp` (≤ 120 s after `iat`), unique `id`; receiver rejects seen IDs for 10 min; response echoes the request `id` and `nonce`. |
| Caller identity | `iss` = registered client ID; the signing key must belong to that client. |

Result: a proxy, log, or packet capture sees only an opaque token. Message type, tenant, plan, and errors are all inside the encryption.

### 3.2 Keys
Each party holds **two key pairs**:

| Key | Type | Purpose |
|---|---|---|
| Signing key | OKP Ed25519 | Signs outgoing messages |
| Encryption key | OKP X25519 | Receives messages encrypted to it |

- Public keys are exchanged at client registration as a JWKS (static file) or fetched from a pinned JWKS URL over TLS.
- Every key has a `kid`. **Rotation:** publish the new key, accept both for an overlap window (default 7 days), then retire the old one. Senders always use the newest key.
- Private keys come from the secret manager or mounted files only [SEC‑007]. Never logged.
- A key‑generation CLI (`python -m protocol.keys generate --client <id>`) outputs a private JWK set and the public JWKS to register.
- Libraries must support RFC 8037 OKP keys: Python `joserfc`, Go `go-jose/v4`, Node `jose`.

### 3.3 Transport rules
- Single endpoint per side:
  - AMS: `POST {AMS_URL}` (e.g. `https://ams.example/ams/v1/msg`)
  - CMMS callback: `POST /internal/ams/v1/msg` (not under `/api`; exposed only to the AMS's network via Nginx allow‑list or a separate internal listener).
- Request and response `Content-Type: application/jose`. Body = compact JWE.
- A decryptable exchange **always returns HTTP 200** with an encrypted response, even for errors.
- Undecryptable or unverifiable input → HTTP `400` with an **empty body** (nothing is revealed). Oversized → `413`. Overloaded → `503` + `Retry-After`. No plaintext bodies are ever sent.
- Max message size: 256 KB.

---

## 4. ENVELOPE

### 4.1 JOSE headers
```
JWE header: { "alg": "ECDH-ES+A256KW", "enc": "A256GCM", "kid": "<receiver enc kid>", "cty": "ams+jws", "typ": "ams+jwe" }
JWS header: { "alg": "EdDSA", "kid": "<sender sig kid>", "typ": "ams+json" }
```

### 4.2 Payload (inside the JWS)
```json
{
  "v": 1,
  "type": "entitlement.get",
  "kind": "request",
  "id": "01926f3e-7c1a-7b4e-9a51-2b7f0c9d1e22",
  "corr": null,
  "iss": "cmms-ir-1",
  "aud": "ams",
  "iat": 1790000000,
  "exp": 1790000060,
  "nonce": "b64url-16-bytes",
  "body": { }
}
```

| Field | Rule |
|---|---|
| `v` | Protocol major version. Receiver rejects unsupported majors with `VERSION_UNSUPPORTED`. |
| `type` | Message type (§5). |
| `kind` | `request`, `response`, `event` (push), `ack`, `error`. |
| `id` | UUIDv7, unique per message. |
| `corr` | For `response`/`ack`/`error`: the `id` being answered. Otherwise `null`. |
| `iss` / `aud` | Sender client ID / receiver ID. Receiver checks `aud` is itself and `iss` matches the signing key owner. |
| `iat` / `exp` | Unix seconds. Clock skew tolerance ±60 s. |
| `nonce` | Random. A response echoes the request's nonce. |
| `body` | Type‑specific object (§5–6). |

**Compatibility:** within a major version, fields are only added. Receivers **ignore unknown fields** and unknown `limits`/`features` keys.

---

## 5. MESSAGE CATALOGUE

Direction: **C** = CMMS, **A** = AMS.

| Type | Dir | Kind | Purpose | Idempotent by |
|---|---|---|---|---|
| `sys.hello` | C→A, A→C | request/response | Handshake: supported versions, key IDs, server time, AMS capabilities. Sent at CMMS boot and every hour. | — |
| `account.provision` | C→A | request/response | Register a new tenant; returns `account_ref` and the initial entitlement. | `tenant_ref` |
| `account.update` | C→A | request/response | Tenant country, currency, locale, or edition changed. | `tenant_ref` + `revision` |
| `account.close` | C→A | request/response | Tenant closed (ORG‑015) or restored within the window. | `tenant_ref` + `action` |
| `entitlement.get` | C→A | request/response | Fetch the current entitlement of one tenant. | — (read) |
| `entitlement.batch_get` | C→A | request/response | Resync up to 500 tenants; optionally only those changed since a revision watermark. | — (read) |
| `entitlement.changed` | A→C | event/ack | Push: an entitlement changed (payment, upgrade, expiry, admin action). | `tenant_ref` + `revision` |
| `usage.report` | C→A | request/ack | Periodic usage counters for metering and policy. | `report_id` |
| `checkout.create` | C→A | request/response | Get a short‑lived URL to the AMS‑hosted payment/upgrade page for the Owner. | `id` |
| `billing.summary.get` | C→A | request/response | Display data for the Owner's Subscription page (plan, status, next renewal, portal link). | — (read) |
| `error` | both | error | Answer to any failed request (§7). | — |

### 5.1 Bodies

**`sys.hello`**
```json
// request
{ "client_version": "1.4.0", "protocol_versions": [1], "sig_kids": ["cmms-ir-1-sig-2026a"], "enc_kids": ["cmms-ir-1-enc-2026a"] }
// response
{ "server_version": "0.1.0", "protocol_versions": [1], "server_time": 1790000001,
  "capabilities": ["entitlement", "usage", "checkout:stub"], "sig_kids": ["ams-sig-2026a"], "enc_kids": ["ams-enc-2026a"] }
```

**`account.provision`**
```json
// request
{ "tenant_ref": "9f1c…", "country": "IR", "currency": "IRR", "locale": "fa",
  "edition": "SAAS", "created_at": "2026-09-25T08:00:00Z", "trial_requested": true,
  "billing_contact": null }              // optional {name, email}; only with Owner consent
// response
{ "account_ref": "acc_7Q…", "entitlement": { /* §6 */ } }
```

**`account.update`**
```json
{ "tenant_ref": "9f1c…", "revision": 3, "country": "IR", "currency": "IRR", "locale": "en" }
```

**`account.close`**
```json
{ "tenant_ref": "9f1c…", "action": "CLOSE", "effective_at": "2026-10-01T00:00:00Z", "reason": "OWNER_REQUEST" }
// action: CLOSE | RESTORE | PURGE
```

**`entitlement.get`**
```json
// request
{ "tenant_ref": "9f1c…" }
// response
{ "entitlement": { /* §6 */ } }
```

**`entitlement.batch_get`**
```json
// request
{ "tenant_refs": ["9f1c…", "…"], "changed_since": null }   // or tenant_refs: null + changed_since: <server watermark>
// response
{ "entitlements": [ /* §6 */ ], "missing": ["…"], "watermark": "2026-09-25T08:05:00.123Z", "has_more": false }
```

**`entitlement.changed`** (AMS → CMMS)
```json
// event
{ "entitlement": { /* §6 */ }, "cause": "PAYMENT_RECEIVED" }
// cause: PAYMENT_RECEIVED | PAYMENT_OVERDUE | SUSPENDED | PLAN_CHANGED | TRIAL_ENDED | PERIOD_RENEWED | ADMIN_OVERRIDE | POLICY_CHANGED
// ack
{ "tenant_ref": "9f1c…", "applied_revision": 42 }
```

**`usage.report`**
```json
{ "report_id": "01926f…", "tenant_ref": "9f1c…",
  "period": { "from": "2026-09-25T00:00:00Z", "to": "2026-09-26T00:00:00Z" },
  "metrics": {
    "assets.active": 312, "org_units.sub": 2, "users.active": 41,
    "ai.credits.used": 640, "ai.tokens.in": 182000, "ai.tokens.out": 41000,
    "storage.bytes": 5368709120, "notify.sms.sent": 17, "mcp.calls": 930
  } }
```
Metric keys use the same naming as `limits` (§6.2). Unknown keys are stored by the AMS and ignored if not used.

**`checkout.create`**
```json
// request
{ "tenant_ref": "9f1c…", "actor_ref": "u_opaque…", "intent": "UPGRADE",
  "target_plan": "PRO", "return_url": "https://app.example/settings/subscription", "locale": "fa" }
// intent: UPGRADE | RENEW | PAY_INVOICE | MANAGE
// response
{ "url": "https://ams.example/checkout/cs_…", "expires_at": "2026-09-25T08:15:00Z" }
```
The Owner is redirected to the AMS page, which selects the payment provider for the account's country. The CMMS never sees card or bank data.

**`billing.summary.get`**
```json
// response
{ "plan": { "code": "ENTERPRISE", "name": { "fa": "سازمانی", "en": "Enterprise" } },
  "status": "CURRENT", "period_ends_at": null, "next_amount": null, "currency": "IRR",
  "portal_url": null, "notices": [] }
```

---

## 6. THE ENTITLEMENT OBJECT

### 6.1 Shape
```json
{
  "tenant_ref": "9f1c…",
  "account_ref": "acc_7Q…",
  "revision": 42,
  "issued_at": "2026-09-25T08:00:00Z",
  "valid_until": "2026-09-26T08:00:00Z",
  "grace_until": "2026-10-02T08:00:00Z",
  "plan": { "code": "ENTERPRISE", "name": { "fa": "سازمانی", "en": "Enterprise" }, "quantity": null },
  "status": "CURRENT",
  "period": { "starts_at": "2026-09-25T00:00:00Z", "ends_at": null, "trial_ends_at": null },
  "limits": {
    "assets.active.max": null,
    "org_units.sub.max": null,
    "users.max": null,
    "ai.credits.monthly": null,
    "storage.bytes.max": null,
    "notify.sms.monthly": null,
    "mcp.calls.monthly": null,
    "audit.retention_days": null
  },
  "features": {
    "inventory": true, "inventory.basic_only": false, "purchasing": true,
    "ai.rag": true, "ai.generation": true, "ai.troubleshoot": true, "ai.autofill": true, "ai.privacy_mode": true,
    "mcp.read": true, "mcp.write": true,
    "consolidated_reports": true, "scheduled_reports": true, "exports.xlsx_pdf": true, "audit.export": true,
    "notify.web_push": true, "notify.email": true, "notify.sms": true, "notify.webhook": true,
    "data_residency": false
  },
  "blocked_actions": [],
  "notices": []
}
```

### 6.2 Field rules
| Field | Rule |
|---|---|
| `revision` | Monotonic per tenant. The CMMS applies an entitlement only if its revision is higher than the cached one. |
| `valid_until` | The CMMS refreshes before this time. |
| `grace_until` | After `valid_until`, the CMMS may keep using this entitlement until `grace_until` if the AMS is unreachable. |
| `plan.code` | `FREE`, `PRO`, `PREMIUM`, `ENTERPRISE` (see `account level policy.md` §2). Display and audit only. **Never used for enforcement.** |
| `plan.quantity` | Committed asset quantity for per‑asset pricing (policy §3.2); `null` for Free and contract‑based Enterprise. Display only; the enforced value is `limits.assets.active.max`. |
| `status` | `TRIAL`, `CURRENT`, `OVERDUE`, `SUSPENDED`, `CLOSED`. The CMMS maps status to default restrictions (COM‑008): OVERDUE blocks `ticket.create`; SUSPENDED blocks all writes except payment, export, and profile. |
| `period.ends_at` | `null` = no end. "Remaining duration" shown in the UI = `ends_at − now`. |
| `limits` | `null` = unlimited. An integer = hard ceiling. A **missing key** falls back to the CMMS's built‑in default for that key (documented in the enforcement registry, §8.3). |
| `features` | `true`/`false`. A missing key = CMMS default for that key. |
| `blocked_actions` | Extra command names the AMS wants blocked (e.g. country rules), added to the status defaults. Lets future AMS policies restrict actions without a CMMS release. |
| `notices` | Optional messages to show the Owner: `{ "code": "TRIAL_ENDING", "level": "WARNING", "text": {fa, en}, "until": … }`. |

Key naming: `<area>.<object>[.<qualifier>]`, lower‑case, dot‑separated.

### 6.3 Values per level
The value of every limit and feature key for each plan is defined in **`account level policy.md` §4 (Account level assignment table)**. The AMS policy engine builds entitlements from that table (plus committed quantity, add‑ons, and contract overrides). This protocol document defines only the keys and their meaning.

---

## 7. ERRORS

```json
{ "code": "UNKNOWN_TENANT", "message": "Tenant is not provisioned", "retryable": false, "retry_after": null, "details": {} }
```

| Code | Meaning | Retryable |
|---|---|---|
| `INVALID_MESSAGE` | Body fails the JSON Schema | No |
| `VERSION_UNSUPPORTED` | `v` not supported; `details.supported` lists versions | No |
| `UNAUTHORIZED` | Client not registered, revoked, or key not valid for `iss` | No |
| `REPLAY` | `id` already seen or message expired | No (resend with new `id`) |
| `UNKNOWN_TENANT` | `tenant_ref` not provisioned → the CMMS re‑sends `account.provision` | No |
| `CONFLICT` | Stale revision in `account.update` | No |
| `NOT_AVAILABLE` | Feature not implemented by this AMS (e.g. checkout in the stub) | No |
| `RATE_LIMITED` | Too many requests | Yes (`retry_after`) |
| `INTERNAL` | AMS failure | Yes |

---

## 8. CMMS‑SIDE INTEGRATION

### 8.1 Components
```
server/.../commercial/
  ports.py        EntitlementPort: current(tenant_id) → Entitlement ; provision / close / checkout / summary
  adapters/
    remote.py     HTTP + JOSE client (protocol/)
    static.py     fixed entitlement for self-hosted/dev
  cache.py        tenant_entitlements table access
  guard.py        EntitlementGuard: require_feature(), check_limit(), check_action()
  registry.py     enforcement registry: key → default, counter source, error code
  callbacks.py    /internal/ams/v1/msg handler (entitlement.changed)
  jobs.py         refresh_due, retry_provision, report_usage
```
This replaces the tier/payment services previously planned inside TENANCY. TENANCY keeps org units, memberships, and invitations.

### 8.2 Local cache (source of truth for enforcement)
```
ams_links(tenant_id PK, tenant_ref UNIQUE, account_ref, provision_state PENDING|DONE, created_at)
tenant_entitlements(tenant_id PK, revision, payload jsonb, signed_jws text,
                    valid_until, grace_until, fetched_at, source REMOTE|STATIC|PROVISIONAL)
```
- `tenant_ref` is a random UUID created by the CMMS. The AMS never sees `tenant_id`.
- `signed_jws` keeps the AMS‑signed inner token, so the cached entitlement is tamper‑evident and auditable.
- **Enforcement reads only this table.** There is no AMS network call on any user request.
- Changes are audited (`tenancy.entitlement_changed`, with old/new revision and cause).

### 8.3 Enforcement registry
| Key | CMMS default if missing | Checked at | Error |
|---|---|---|---|
| `assets.active.max` | 100 | asset create, restore, recommission, import commit, zone clone | `TIER_LIMIT_REACHED` |
| `org_units.sub.max` | 0 | sub‑org create | `TIER_LIMIT_REACHED` |
| `users.max` | 5 (requesters never counted) | invitation accept, role change to a full role | `TIER_LIMIT_REACHED` |
| `ai.credits.monthly` | 50 | AI request (credits per action: policy §6) | `AI_QUOTA_EXCEEDED` |
| `storage.bytes.max` | 2 GB | upload complete | `STORAGE_QUOTA_EXCEEDED` |
| `notify.sms.monthly` | 0 | SMS delivery | delivery `SUPPRESSED` (quota) |
| `mcp.calls.monthly` | 1,000 | MCP call | `MCP_QUOTA_EXCEEDED` |
| `audit.retention_days` | 90 | audit purge job | — |
| `mcp.write` | false | MCP write tools | `FEATURE_NOT_IN_PLAN` |
| other feature keys (`purchasing`, `ai.troubleshoot`, `consolidated_reports`, …) | Free‑level value | owning command / endpoint | `FEATURE_NOT_IN_PLAN` |
| status `OVERDUE` | — | `ticket.create` | `TENANT_OVERDUE` |
| status `SUSPENDED` | — | all writes except payment/export/profile | `TENANT_SUSPENDED` |

**Missing‑key defaults equal the Free level** of `account level policy.md` §4, so an incomplete entitlement never grants more than Free.

Adding a policy = add a row here + a check in the owning command. The protocol does not change.

### 8.4 Refresh flow
1. **Push:** `entitlement.changed` → verify → apply if higher revision → ack.
2. **Scheduled:** job `commercial.refresh_due` every `AMS_REFRESH_INTERVAL_SECONDS` (default 300) batch‑fetches tenants whose `valid_until` is within 20% of its lifetime.
3. **Reconcile:** nightly `entitlement.batch_get` with `changed_since` watermark catches missed pushes.
4. **Provision:** tenant creation writes `ams_links(provision_state=PENDING)` and a provisional entitlement (`AMS_PROVISIONAL_PLAN`) in the same transaction; a queued job sends `account.provision` and retries until done.
5. **Usage:** daily `usage.report` per tenant (idempotent `report_id`).

---

## 9. FAILURE BEHAVIOUR (RESILIENCE)

| Situation | CMMS behaviour |
|---|---|
| AMS slow or down | Keep using the cached entitlement. Requests retry with backoff (timeout `AMS_TIMEOUT_SECONDS`, default 5). `/health/ready` reports AMS as **DEGRADED**, never failed. Alert after 15 min. |
| Past `valid_until`, before `grace_until` | Keep the cached entitlement. Warning metric. |
| Past `grace_until` | Apply `AMS_STALE_POLICY`: `keep_last` (default — keep enforcing the last entitlement) or `restrict` (treat as SUSPENDED). **Reads and data export are never blocked.** |
| New tenant while AMS down | Provisional entitlement from `AMS_PROVISIONAL_PLAN`; provisioning retried by the queue. |
| Push lost | Nightly reconcile (§8.4.3). |
| Duplicate / out‑of‑order push | Ignored by revision check. |
| CMMS moved to another host | Nothing to do on the AMS: the client identity is the key, not the IP. Only update the callback URL in the AMS client registry. |
| AMS moved to another host | Change `AMS_URL`. Keys stay the same. |
| Key compromise | Revoke the client in the AMS registry, generate new keys, re‑register. Cached entitlements stay valid until `grace_until`. |

---

## 10. MVP STUB BEHAVIOUR

The MVP AMS is a small FastAPI app (`ams/`) implementing the **full envelope, crypto, replay protection, schema validation, and client registry**, but a trivial policy:

| Message | Stub response |
|---|---|
| `sys.hello` | Real handshake. `capabilities: ["entitlement","usage","checkout:stub"]`. |
| `account.provision` | Creates `account_ref` (stored). Returns ENTERPRISE entitlement. |
| `account.update` / `account.close` | Stored, acknowledged. |
| `entitlement.get` / `batch_get` | **Every tenant: `plan.code = ENTERPRISE`, `status = CURRENT`, all limits `null` (unlimited), all features `true`, `period.ends_at = null`**, `valid_until = now + 24 h`, `grace_until = now + 7 d`, `revision = 1`. |
| `entitlement.changed` | Not sent (no policy changes exist). An admin CLI can send one for testing. |
| `usage.report` | Stored, acknowledged. |
| `checkout.create` | `error NOT_AVAILABLE`. |
| `billing.summary.get` | ENTERPRISE, CURRENT, no amounts. |

Because the stub is protocol‑complete, the future policy engine replaces only the "compute entitlement" function.

---

## 11. CONFIGURATION

### 11.1 CMMS (`.env`)
```
AMS_MODE=remote                         # remote | static
AMS_URL=https://ams.internal:8200/ams/v1/msg
AMS_CLIENT_ID=cmms-ir-1
AMS_SIGNING_KEY_FILE=/run/secrets/cmms_ams_sig.jwk        # private Ed25519
AMS_ENCRYPTION_KEY_FILE=/run/secrets/cmms_ams_enc.jwk     # private X25519
AMS_PEER_JWKS_FILE=/run/secrets/ams_public.jwks           # or AMS_PEER_JWKS_URL (+ AMS_PEER_JWKS_PIN)
AMS_TIMEOUT_SECONDS=5
AMS_REFRESH_INTERVAL_SECONDS=300
AMS_STALE_POLICY=keep_last              # keep_last | restrict
AMS_PROVISIONAL_PLAN=ENTERPRISE         # entitlement template used before provisioning completes
AMS_STATIC_PLAN=ENTERPRISE              # static mode only
AMS_CALLBACK_ENABLED=true
AMS_MTLS_CERT_FILE= AMS_MTLS_KEY_FILE= AMS_MTLS_CA_FILE=  # optional
```

### 11.2 AMS (`.env`)
```
AMS_DB_URL=postgresql://…/ams
AMS_SERVER_ID=ams
AMS_SIGNING_KEY_FILE=/run/secrets/ams_sig.jwk
AMS_ENCRYPTION_KEY_FILE=/run/secrets/ams_enc.jwk
AMS_CLIENTS_FILE=/etc/ams/clients.yaml     # client_id → public JWKS, callback URL, status
AMS_POLICY=stub                            # stub | engine (future)
AMS_REPLAY_WINDOW_SECONDS=600
AMS_ENTITLEMENT_TTL_HOURS=24
AMS_GRACE_DAYS=7
```

---

## 12. FUTURE AMS INTERNALS (NOT IN MVP)

Outline only, so the protocol is not blocked by them:
- **Data:** accounts, plans, plan_prices (per country/currency), subscriptions, invoices, payments, credits/vouchers, policy rules, client registry, audit log.
- **Payment providers** behind an adapter, selected by account country (e.g. an Iranian Shaparak‑connected gateway for IRR, an international card processor elsewhere) [D2].
- **Policy engine:** computes the entitlement from subscription + payments + country rules + admin overrides; emits `entitlement.changed` on every change.
- **Admin console** for plans, overrides, and refunds (replaces tier/payment editing in the CMMS admin console, OPS‑007).
- **Hosted pages:** checkout, billing portal, invoices, localized fa/en.

---

## 13. TESTING

| Test | Where |
|---|---|
| JSON Schema validation for every message type | `protocol/` |
| **Shared test vectors**: fixed keys + plaintext + expected verify/decrypt results, incl. tampered, expired, replayed, wrong‑`aud`, wrong‑key cases | `protocol/vectors/` — run by both CMMS and AMS (and any future re‑implementation) |
| Contract tests: CMMS remote adapter ↔ stub AMS in Compose | CI |
| Resilience tests: AMS down, past `valid_until`, past `grace_until`, out‑of‑order revisions, provisioning retry | CMMS integration suite |
| Enforcement tests: every row of §8.3 with limit = 0 / N / null | CMMS unit suite |
