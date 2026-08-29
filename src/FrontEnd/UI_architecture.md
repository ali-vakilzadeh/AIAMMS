# CMMS SaaS — Web UI Architecture & Implementation Plan

## Complete Frontend Blueprint for React SPA

---

## Table of Contents

1. [Overview & Design Philosophy](#1-overview--design-philosophy)
2. [Technology Stack & Tooling](#2-technology-stack--tooling)
3. [Project Structure](#3-project-structure)
4. [Design System & Component Library](#4-design-system--component-library)
5. [Global Layout Architecture](#5-global-layout-architecture)
6. [State Management Strategy](#6-state-management-strategy)
7. [API Integration Layer](#7-api-integration-layer)
8. [Authentication & Authorization](#8-authentication--authorization)
9. [Tab Workspace System](#9-tab-workspace-system)
10. [Left Asset Tree Band](#10-left-asset-tree-band)
11. [Right AI Side-Band](#11-right-ai-side-band)
12. [RTL/LTR Bi-Directional Support](#12-rtlltr-bi-directional-support)
13. [Page-by-Page Component Architecture](#13-page-by-page-component-architecture)
14. [Role-Based UI Visibility](#14-role-based-ui-visibility)
15. [Error Handling & UX Patterns](#15-error-handling--ux-patterns)
16. [Testing Strategy](#16-testing-strategy)
17. [Build, CI/CD & Deployment](#17-build-cicd--deployment)
18. [Implementation Roadmap (Wave Plan)](#18-implementation-roadmap-wave-plan)

---

## 1. Overview & Design Philosophy

### 1.1 Application Paradigm

The CMMS Web UI is **not** a traditional multi-page website. It is a **persistent workspace application** modeled after IDE-style interfaces (e.g., VS Code, browser DevTools). The user logs in once and operates within a single shell that persists across all interactions.

**Core principles:**
- **Workspace, not pages**: Content opens as tabs within a persistent shell. The shell (header, asset tree, AI panel) never unmounts.
- **Asset-centric navigation**: The primary navigation metaphor is the hierarchical asset tree (Zone → System → Sub-system → Node), not a menu of pages.
- **AI is omnipresent**: The AI assistant is a persistent, collapsible side-band available on every tab, contextually aware of the active asset or document.
- **Server-aligned**: Every UI action maps 1:1 to a server API endpoint. The frontend owns zero business logic — it is a pure presentation and orchestration layer.
- **Role-reactive**: The UI dynamically shows/hides elements based on the authenticated user's role (Operator, Maintenance, Manager, Reporter, SysAdmin).

### 1.2 Relationship to Server Architecture

| Server Concept | UI Counterpart |
|---|---|
| `API` module (FastAPI, `/api/v1`) | Axios HTTP client with interceptors |
| `AUTH` module (JWT + refresh cookie) | Auth context, token interceptor, login/logout pages |
| `TENANCY` module (RLS, org scope) | Automatic — server enforces via cookie/session; UI passes no org_id |
| `ASSETS` module | Left Asset Tree Band + Zone/System/Node detail tabs |
| `TEMPLATES` module | Workflow/Checklist editor tabs |
| `CYCLES` module | Cycles management tab |
| `WORKORDERS` module | WO list + WO execution tabs |
| `TICKETS` module | Ticket list + ticket detail/feedback tabs |
| `AI` module | Right AI Side-Band (RAG chat + checklist generation) |
| `NOTIFY` module | Notification bell + notification center tab |
| `REPORTS` module | Reports & KPIs tab |
| `FILES` module | File uploader components within asset/ticket tabs |
| `AUDIT` module | Audit log tab |
| `MCP` module | Not directly consumed by UI (external tool integration) |

---

## 2. Technology Stack & Tooling

### 2.1 Core Dependencies

| Category | Technology | Version | Rationale |
|---|---|---|---|
| Framework | React | 18+ | Specified in architecture.txt |
| Language | TypeScript | 5.x | Type safety for complex domain models |
| Build Tool | Vite | 5.x | Fast HMR, native ESM, specified in architecture.txt |
| Styling | Tailwind CSS | 3.x+ | Utility-first, logical properties for RTL/LTR |
| Server State | TanStack React Query | 5.x | Caching, invalidation, background refetch, specified in architecture.txt |
| UI State | Zustand | 4.x | Lightweight, no boilerplate, ideal for tab/tree/panel state |
| HTTP Client | Axios | 1.x | Interceptors for auth refresh, error envelope parsing |
| Forms | React Hook Form + Zod | 7.x + 3.x | Performant forms with schema validation matching server rules |
| Routing | TanStack Router | 1.x | Type-safe routing; used for initial auth pages only (workspace uses tab system) |
| QR Scanner | html5-qrcode | 2.x | HTML5 camera-based scanning, specified in architecture.txt |
| Charts | Recharts | 2.x | React-native charting, composable, lightweight |
| Tables | TanStack Table | 8.x | Headless, powerful sorting/filtering/pagination |
| Tree View | Custom (recursive) | — | Tailwind-styled recursive component with lazy loading |
| Rich Text / Signature | react-signature-canvas | 1.x | Digital signature capture for WO execution |
| Date/Time | date-fns | 3.x | Timezone-aware formatting, lightweight |
| i18n (future) | react-i18next | — | Scaffolded but not MVP; RTL/LTR handled via CSS |
| Icons | Lucide React | — | Consistent, tree-shakeable icon set |

### 2.2 Dev Tooling

| Tool | Purpose |
|---|---|
| ESLint + @typescript-eslint | Linting |
| Prettier | Code formatting |
| Vitest | Unit and component testing |
| Testing Library (@testing-library/react) | Component tests |
| Playwright | End-to-end tests |
| Storybook | Component documentation and visual testing |
| MSW (Mock Service Worker) | API mocking for tests and development |
| OpenAPI TypeScript Codegen | Generate TypeScript types from server's OpenAPI spec |

### 2.3 Environment Configuration

```
VITE_API_BASE_URL=https://api.example.com/api/v1
VITE_WS_URL=wss://api.example.com/ws
VITE_APP_TITLE=CMMS Platform
```

Vite's `import.meta.env` is used. No runtime config injection needed for MVP (environment is baked at build time).

---

## 3. Project Structure

```
src/
├── main.tsx                          # Entry point, mounts App
├── App.tsx                           # Root: providers, layout router
├── vite-env.d.ts
│
├── api/                              # API integration layer
│   ├── client.ts                     # Axios instance, interceptors
│   ├── endpoints/                    # One file per server module
│   │   ├── auth.ts                   # /auth/*
│   │   ├── organizations.ts          # /organizations/*
│   │   ├── assets.ts                 # /zones, /systems, /sub-systems, /service-points
│   │   ├── templates.ts             # /templates/*
│   │   ├── cycles.ts                # /cycles/*
│   │   ├── workorders.ts            # /workorders/*
│   │   ├── tickets.ts               # /tickets/*
│   │   ├── files.ts                 # /files/*
│   │   ├── notifications.ts         # /notifications/*
│   │   ├── reports.ts              # /reports/*
│   │   ├── audit.ts                # /audit/*
│   │   └── ai.ts                   # /ai/*
│   ├── types/                       # Generated from OpenAPI spec
│   │   ├── generated.ts            # Auto-generated types
│   │   └── ui.ts                   # UI-specific types (tab defs, tree nodes)
│   └── hooks/                       # React Query hooks
│       ├── useAuth.ts
│       ├── useAssets.ts
│       ├── useWorkOrders.ts
│       ├── useTickets.ts
│       ├── useTemplates.ts
│       ├── useCycles.ts
│       ├── useNotifications.ts
│       ├── useReports.ts
│       ├── useAI.ts
│       └── useAudit.ts
│
├── stores/                          # Zustand stores (UI state only)
│   ├── useTabStore.ts               # Tab workspace state
│   ├── useTreeStore.ts              # Asset tree expansion/selection state
│   ├── useAIPanelStore.ts           # AI side-band open/close/context
│   ├── useLayoutStore.ts            # RTL/LTR, sidebar collapse states
│   └── useNotificationStore.ts      # Unread count, WebSocket state
│
├── auth/                            # Authentication subsystem
│   ├── AuthProvider.tsx             # Context provider wrapping auth state
│   ├── useAuthContext.ts            # Hook to access auth state
│   ├── RequireAuth.tsx              # Route guard component
│   ├── RequireRole.tsx              # Role-based visibility wrapper
│   └── tokenManager.ts             # Access token in-memory management
│
├── layout/                          # Global shell components
│   ├── AppShell.tsx                 # Master layout: header + tree + workspace + AI
│   ├── Header.tsx                   # Top bar: logo, search, bell, user menu, RTL toggle
│   ├── TabBar.tsx                   # Firefox-style tab strip
│   ├── TabContent.tsx               # Renders active tab's component
│   ├── AssetTree.tsx                # Left collapsible tree band
│   ├── AssetTreeNode.tsx            # Recursive tree node component
│   ├── AISideBand.tsx              # Right collapsible AI panel
│   └── WorkspaceArea.tsx           # Central content area
│
├── pages/                           # Page components (one per tab type)
│   ├── auth/
│   │   ├── LoginPage.tsx
│   │   ├── SignupPage.tsx
│   │   ├── EmailVerificationPage.tsx
│   │   ├── ForgotPasswordPage.tsx
│   │   └── ResetPasswordPage.tsx
│   ├── dashboard/
│   │   └── DashboardPage.tsx
│   ├── zones/
│   │   ├── ZoneListPage.tsx
│   │   └── ZoneDetailPage.tsx
│   ├── systems/
│   │   └── SystemDetailPage.tsx
│   ├── nodes/
│   │   └── NodeDetailPage.tsx
│   ├── qr/
│   │   └── QRScannerPage.tsx
│   ├── workorders/
│   │   ├── WorkOrderListPage.tsx
│   │   └── WorkOrderExecutionPage.tsx
│   ├── templates/
│   │   ├── TemplateListPage.tsx
│   │   └── TemplateEditorPage.tsx
│   ├── cycles/
│   │   └── CyclesPage.tsx
│   ├── tickets/
│   │   ├── TicketListPage.tsx
│   │   └── TicketDetailPage.tsx
│   ├── reports/
│   │   └── ReportsPage.tsx
│   ├── settings/
│   │   ├── OrgSettingsPage.tsx
│   │   └── UserProfilePage.tsx
│   ├── notifications/
│   │   └── NotificationsPage.tsx
│   └── audit/
│       └── AuditLogPage.tsx
│
├── components/                      # Shared/reusable UI components
│   ├── ui/                          # Primitive design system components
│   │   ├── Button.tsx
│   │   ├── Input.tsx
│   │   ├── SecureInput.tsx
│   │   ├── Select.tsx
│   │   ├── MultiSelect.tsx
│   │   ├── Checkbox.tsx
│   │   ├── Toggle.tsx
│   │   ├── Badge.tsx
│   │   ├── Card.tsx
│   │   ├── Modal.tsx
│   │   ├── Drawer.tsx
│   │   ├── Table.tsx               # Wrapper around TanStack Table
│   │   ├── Tabs.tsx
│   │   ├── Alert.tsx
│   │   ├── Spinner.tsx
│   │   ├── Skeleton.tsx
│   │   ├── Tooltip.tsx
│   │   ├── Dropdown.tsx
│   │   ├── FileUploader.tsx
│   │   ├── SignaturePad.tsx
│   │   ├── Pagination.tsx
│   │   ├── SearchInput.tsx
│   │   ├── EmptyState.tsx
│   │   └── ConfirmDialog.tsx
│   ├── domain/                      # Domain-specific composite components
│   │   ├── StatusBadge.tsx          # Maps WO/ticket/node statuses to colors
│   │   ├── SafetyFlagBadge.tsx      # HOT_INSPECT, PAUSE, STOP_UNTIL_COMPLETE
│   │   ├── PriorityBadge.tsx        # LOW, MEDIUM, HIGH, CRITICAL
│   │   ├── RoleBadge.tsx
│   │   ├── CounterDisplay.tsx
│   │   ├── KPICard.tsx
│   │   ├── ChartWrapper.tsx
│   │   ├── MeasurementInput.tsx     # Numeric/Text/Boolean per item type
│   │   ├── CycleTriggerConfig.tsx
│   │   ├── TicketFeedbackLoop.tsx
│   │   ├── AIPromptModal.tsx
│   │   ├── AIDraftPreview.tsx
│   │   ├── AICitationList.tsx
│   │   ├── ExportButton.tsx
│   │   └── CloneProgressIndicator.tsx
│   └── forms/                       # Reusable form sections
│       ├── ZoneForm.tsx
│       ├── SystemForm.tsx
│       ├── NodeForm.tsx
│       ├── CycleForm.tsx
│       ├── TemplateItemRow.tsx
│       ├── TicketReportForm.tsx
│       ├── FeedbackForm.tsx
│       ├── UserInviteForm.tsx
│       └── PasswordForm.tsx
│
├── lib/                             # Pure utility functions
│   ├── constants.ts                 # Roles, statuses, enums (mirrors shared/enums.py)
│   ├── permissions.ts               # Role → capability matrix
│   ├── formatters.ts                # Date, number, duration formatters
│   ├── validators.ts                # Zod schemas matching server validation
│   ├── cn.ts                        # clsx + tailwind-merge utility
│   └── storage.ts                   # localStorage wrapper (preferences only)
│
├── styles/
│   ├── globals.css                  # Tailwind directives, CSS variables, RTL rules
│   └── fonts.css                    # Font face declarations
│
└── test/
    ├── setup.ts                     # Vitest setup, MSW server
    ├── mocks/
    │   ├── handlers.ts              # MSW request handlers
    │   └── data.ts                  # Fixture data
    └── utils/
        └── renderWithProviders.tsx   # Test render wrapper
```

---

## 4. Design System & Component Library

### 4.1 Design Tokens (CSS Variables in `globals.css`)

```css
:root {
  /* Spacing scale */
  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-6: 1.5rem;
  --space-8: 2rem;

  /* Layout dimensions */
  --header-height: 3.5rem;
  --tab-bar-height: 2.5rem;
  --tree-band-width: 18rem;
  --tree-band-collapsed-width: 3rem;
  --ai-band-width: 24rem;
  --ai-band-expanded-width: 50vw;
  --ai-band-collapsed-width: 3rem;

  /* Status colors */
  --color-active: #22c55e;
  --color-inactive: #9ca3af;
  --color-warning: #f59e0b;
  --color-critical: #ef4444;
  --color-info: #3b82f6;

  /* Safety flag colors */
  --color-hot-inspect: #f97316;
  --color-pause: #eab308;
  --color-stop: #dc2626;

  /* Priority colors */
  --color-low: #6b7280;
  --color-medium: #3b82f6;
  --color-high: #f59e0b;
  --color-critical-priority: #dc2626;
}
```

### 4.2 Component API Convention

All primitive components follow this pattern:

```tsx
interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
  icon?: React.ReactNode;
}
```

- Every component accepts `className` for Tailwind overrides.
- Every component uses `React.forwardRef` for ref forwarding.
- All interactive components have proper `aria-*` attributes.

### 4.3 Tailwind RTL Strategy

Use **logical properties** exclusively:

```css
/* ✅ DO: Logical properties */
.ms-4 { margin-inline-start: 1rem; }
.pe-2 { padding-inline-end: 0.5rem; }
.text-start { text-align: start; }
.rounded-s-lg { border-start-start-radius: 0.5rem; border-end-start-radius: 0.5rem; }

/* ❌ DON'T: Physical properties */
.ml-4 { margin-left: 1rem; }
.pr-2 { padding-right: 0.5rem; }
.text-left { text-align: left; }
```

Tailwind v3.3+ supports logical properties natively with `ms-`, `me-`, `ps-`, `pe-`, `start-`, `end-` prefixes. The `dir` attribute on `<html>` controls direction.

---

## 5. Global Layout Architecture

### 5.1 Shell Structure

```
┌──────────────────────────────────────────────────────────────────────┐
│  HEADER (fixed, full width, z-50)                                  │
│  [Logo] [Global Search] [RTL Toggle] [🔔 Bell] [User Avatar ▾]    │
├──────────────────────────────────────────────────────────────────────┤
│  TAB BAR (below header, full width, z-40)                         │
│  [Dashboard ×] [Zone: HQ ×] [WO-0042 ×] [AI Chat ×] [+]          │
├──────────┬─────────────────────────────────────────┬───────────────┤
│  LEFT    │                                         │  RIGHT      │
│  ASSET   │         MAIN WORKSPACE                  │  AI         │
│  TREE    │         (active tab content)            │  SIDE-BAND  │
│  BAND    │                                         │             │
│          │                                         │             │
│  📁 Zones│                                         │  💬 Chat    │
│   ├ HQ   │   ┌─────────────────────────────┐       │  Context:   │
│   │ ├ Sys│   │                             │       │  Node: P-01 │
│   │ │ ├ N│   │   Tab Content Renders Here  │       │             │
│   │ ├ Sys│   │                             │       │  [Type msg] │
│   ├ Brnch│   │                             │       │  [Send]     │
│          │   └─────────────────────────────┘       │             │
│  [◀]     │                                         │  [▶]        │
└──────────┴─────────────────────────────────────────┴───────────────┘
```

### 5.2 Component Hierarchy

```tsx
// App.tsx
<QueryClientProvider>
  <AuthProvider>
    <Router>
      <Route path="/login" component={LoginPage} />
      <Route path="/signup" component={SignupPage} />
      <Route path="/verify-email" component={EmailVerificationPage} />
      <Route path="/forgot-password" component={ForgotPasswordPage} />
      <Route path="/reset-password" component={ResetPasswordPage} />
      <Route path="/" component={RequireAuth}>
        <AppShell />
      </Route>
    </Router>
  </AuthProvider>
</QueryClientProvider>

// AppShell.tsx
<div className="h-screen flex flex-col" dir={layoutDirection}>
  <Header />
  <TabBar />
  <div className="flex flex-1 overflow-hidden">
    <AssetTreeBand />
    <WorkspaceArea>
      <TabContent /> {/* Renders the active tab's page component */}
    </WorkspaceArea>
    <AISideBand />
  </div>
</div>
```

### 5.3 Header Component Detail

| Element | Behavior |
|---|---|
| Logo | Clicking navigates to/focuses the Dashboard tab |
| Global Search | `Cmd/Ctrl+K` shortcut; searches assets, WOs, tickets by code/name; results open as tabs |
| RTL/LTR Toggle | Toggles `dir` attribute on `<html>`, persisted in `useLayoutStore` and `localStorage` |
| Notification Bell | Shows unread count badge; click opens Notifications tab or dropdown |
| User Avatar Dropdown | Shows name, role, org; links to Profile tab; Logout action |

---

## 6. State Management Strategy

### 6.1 State Classification

| State Type | Tool | Examples |
|---|---|---|
| **Server state** (fetched, cached, invalidated) | React Query | Asset lists, WO data, ticket details, KPIs, notifications |
| **UI state** (transient, client-only) | Zustand | Active tab, open tabs list, tree expansion, AI panel open/close |
| **Auth state** (identity, tokens) | React Context + Zustand | User profile, role, access token, permissions |
| **Form state** (input values, validation) | React Hook Form | All forms |
| **URL state** (deep links) | TanStack Router | Auth pages only; workspace uses tab IDs |

### 6.2 Key Store Definitions

```typescript
// stores/useTabStore.ts
interface Tab {
  id: string;                    // Unique tab ID (e.g., "node-detail:abc123")
  type: TabType;                 // Enum of all page types
  title: string;                 // Display title (e.g., "Node: PUMP-01")
  params: Record<string, any>;   // Parameters (e.g., { nodeId: "abc123" })
  pinned?: boolean;
}

interface TabStore {
  tabs: Tab[];
  activeTabId: string | null;
  openTab: (tab: Omit<Tab, 'id'>) => string;  // Opens or focuses existing
  closeTab: (id: string) => void;
  setActiveTab: (id: string) => void;
  pinTab: (id: string) => void;
  reorderTabs: (fromIndex: number, toIndex: number) => void;
}

// stores/useTreeStore.ts
interface TreeStore {
  expandedNodes: Set<string>;    // IDs of expanded tree nodes
  selectedNodeId: string | null;
  toggleExpand: (id: string) => void;
  selectNode: (id: string) => void;
}

// stores/useAIPanelStore.ts
interface AIPanelStore {
  isOpen: boolean;
  isExpanded: boolean;           // Half-screen mode
  context: {                     // Current RAG context
    nodeId?: string;
    manualIds?: string[];
  };
  toggle: () => void;
  setContext: (ctx: Partial<AIPanelStore['context']>) => void;
}
```

### 6.3 React Query Configuration

```typescript
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,           // 30s default stale time
      gcTime: 5 * 60_000,          // 5 min garbage collection
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
});
```

**Invalidation strategy**: Mutations (create/update/delete) invalidate relevant query keys. For example, creating a WO invalidates `['workorders']` and `['dashboard', 'counters']`.

---

## 7. API Integration Layer

### 7.1 Axios Client

```typescript
// api/client.ts
const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  withCredentials: true,          // Send HttpOnly refresh cookie
  headers: { 'Content-Type': 'application/json' },
});

// Request interceptor: attach access token
apiClient.interceptors.request.use((config) => {
  const token = tokenManager.getAccessToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Response interceptor: handle 401 → refresh → retry
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401 && !error.config._retried) {
      error.config._retried = true;
      const newToken = await refreshAccessToken(); // POST /auth/refresh
      tokenManager.setAccessToken(newToken);
      error.config.headers.Authorization = `Bearer ${newToken}`;
      return apiClient(error.config);
    }
    // Parse server error envelope: { error_code, message, details }
    return Promise.reject(parseApiError(error));
  }
);
```

### 7.2 Endpoint Module Pattern

Each file in `api/endpoints/` mirrors a server module:

```typescript
// api/endpoints/workorders.ts
export const workOrderApi = {
  list: (params: WOListParams) =>
    apiClient.get<PaginatedResponse<WorkOrder>>('/workorders', { params }),
  get: (id: string) =>
    apiClient.get<WorkOrder>(`/workorders/${id}`),
  snooze: (id: string, data: SnoozeRequest) =>
    apiClient.post(`/workorders/${id}/snooze`, data),
  complete: (id: string, data: CompleteRequest) =>
    apiClient.post(`/workorders/${id}/complete`, data),
  reject: (id: string, data: RejectRequest) =>
    apiClient.post(`/workorders/${id}/reject`, data),
};
```

### 7.3 React Query Hook Pattern

```typescript
// api/hooks/useWorkOrders.ts
export function useWorkOrders(params: WOListParams) {
  return useQuery({
    queryKey: ['workorders', params],
    queryFn: () => workOrderApi.list(params).then(r => r.data),
  });
}

export function useSnoozeWorkOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: SnoozeRequest }) =>
      workOrderApi.snooze(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workorders'] });
      qc.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });
}
```

### 7.4 Type Generation

Types are generated from the server's OpenAPI spec using `openapi-typescript`:

```bash
npx openapi-typescript http://localhost:8000/openapi.json -o src/api/types/generated.ts
```

This ensures frontend types always match server schemas.

---

## 8. Authentication & Authorization

### 8.1 Auth Flow

```
┌──────────┐    POST /auth/login     ┌──────────┐
│  Login   │ ──────────────────────► │  Server  │
│  Page    │ ◄────────────────────── │  AUTH    │
└──────────┘   200: { access_token } └──────────┘
                    + Set-Cookie: refresh_token (HttpOnly)
     │
     ▼
┌──────────┐
│ Store    │ access_token in memory (tokenManager)
│ Redirect │ to AppShell (workspace)
└──────────┘
```

### 8.2 Token Management

```typescript
// auth/tokenManager.ts
// Access token lives ONLY in memory (never localStorage)
let accessToken: string | null = null;

export const tokenManager = {
  getAccessToken: () => accessToken,
  setAccessToken: (token: string) => { accessToken = token; },
  clear: () => { accessToken = null; },
};
```

The **refresh token** is managed entirely by the server as an `HttpOnly`, `Secure`, `SameSite=Strict` cookie. The frontend never sees it. The "Remember me for 7 days" checkbox sends `{ remember: true }` in the login payload, and the server sets the cookie's `Max-Age` accordingly (7 days vs session).

### 8.3 Auth Context

```typescript
// auth/AuthProvider.tsx
interface AuthState {
  user: User | null;
  role: Role | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string, remember: boolean) => Promise<void>;
  logout: () => Promise<void>;
}
```

On mount, `AuthProvider` calls `GET /auth/me` to restore the session from the refresh cookie. If 401, the user is unauthenticated.

### 8.4 Role-Based Access Control

```typescript
// lib/permissions.ts
export const PERMISSIONS = {
  'workorder.execute': ['Maintenance'],
  'workorder.snooze': ['Maintenance'],
  'workorder.view_all': ['Manager', 'Reporter'],
  'ticket.create': ['Operator', 'Manager'],
  'ticket.claim': ['Maintenance'],
  'ticket.escalate': ['Operator', 'Manager'],
  'ticket.decide': ['Manager'],
  'zone.clone': ['Manager'],
  'cycle.create': ['Manager'],
  'cycle.reset': ['Manager'],
  'template.edit': ['Manager'],
  'ai.generate_checklist': ['Manager'],
  'ai.chat': ['Operator', 'Maintenance', 'Manager'],
  'node.safety_flag': ['Manager', 'Maintenance'],
  'org.manage': ['Manager'],
  'user.invite': ['Manager'],
  'user.remove': ['Manager'],
  'user.change_role': ['Manager'],
  'audit.view': ['Manager', 'SysAdmin'],
  'report.export': ['Manager', 'Reporter'],
} as const;

export function hasPermission(role: Role, permission: string): boolean {
  return PERMISSIONS[permission]?.includes(role) ?? false;
}
```

```tsx
// auth/RequireRole.tsx
export function RequireRole({ permission, children, fallback = null }) {
  const { role } = useAuthContext();
  if (!hasPermission(role, permission)) return fallback;
  return children;
}

// Usage:
<RequireRole permission="workorder.execute">
  <Button>Complete Work Order</Button>
</RequireRole>
```

---

## 9. Tab Workspace System

### 9.1 Tab Identity & Deduplication

Each tab type has a **deduplication key** to prevent opening the same entity twice:

| Tab Type | Dedup Key | Example Tab ID |
|---|---|---|
| Dashboard | `dashboard` (singleton) | `dashboard` |
| Zone Detail | `zone:{id}` | `zone:z-abc123` |
| System Detail | `system:{id}` | `system:s-def456` |
| Node Detail | `node:{id}` | `node:n-ghi789` |
| WO List | `wo-list` (singleton) | `wo-list` |
| WO Execution | `wo-exec:{id}` | `wo-exec:wo-001` |
| Template List | `template-list` (singleton) | `template-list` |
| Template Editor | `template-edit:{id}` | `template-edit:t-002` |
| Cycles | `cycles` (singleton) | `cycles` |
| Ticket List | `ticket-list` (singleton) | `ticket-list` |
| Ticket Detail | `ticket:{id}` | `ticket:tk-003` |
| Reports | `reports` (singleton) | `reports` |
| Org Settings | `org-settings` (singleton) | `org-settings` |
| User Profile | `user-profile` (singleton) | `user-profile` |
| Notifications | `notifications` (singleton) | `notifications` |
| Audit Log | `audit-log` (singleton) | `audit-log` |
| AI Chat | `ai-chat` (singleton) | `ai-chat` |
| QR Scanner | `qr-scanner` (singleton) | `qr-scanner` |

When `openTab()` is called with an existing dedup key, the system **focuses** the existing tab instead of creating a new one.

### 9.2 Tab Bar Component

```tsx
// layout/TabBar.tsx
<div className="flex items-center h-[var(--tab-bar-height)] border-b overflow-x-auto">
  {tabs.map(tab => (
    <TabItem
      key={tab.id}
      title={tab.title}
      isActive={tab.id === activeTabId}
      isPinned={tab.pinned}
      onClick={() => setActiveTab(tab.id)}
      onClose={() => closeTab(tab.id)}
    />
  ))}
  <button onClick={openNewTabMenu}>+</button>
</div>
```

### 9.3 Tab Content Router

```tsx
// layout/TabContent.tsx
const TAB_COMPONENT_MAP: Record<TabType, React.ComponentType<any>> = {
  dashboard: DashboardPage,
  'zone-detail': ZoneDetailPage,
  'system-detail': SystemDetailPage,
  'node-detail': NodeDetailPage,
  'wo-list': WorkOrderListPage,
  'wo-exec': WorkOrderExecutionPage,
  'template-list': TemplateListPage,
  'template-editor': TemplateEditorPage,
  cycles: CyclesPage,
  'ticket-list': TicketListPage,
  'ticket-detail': TicketDetailPage,
  reports: ReportsPage,
  'org-settings': OrgSettingsPage,
  'user-profile': UserProfilePage,
  notifications: NotificationsPage,
  'audit-log': AuditLogPage,
  'qr-scanner': QRScannerPage,
};

export function TabContent() {
  const { activeTabId, tabs } = useTabStore();
  const activeTab = tabs.find(t => t.id === activeTabId);
  if (!activeTab) return <EmptyState />;
  const Component = TAB_COMPONENT_MAP[activeTab.type];
  return <Component {...activeTab.params} />;
}
```

### 9.4 Default Tabs on Login

Upon successful login, the system opens:
1. **Dashboard** (active, pinned)
2. **Notifications** (pinned, background)

---

## 10. Left Asset Tree Band

### 10.1 Data Loading Strategy

The tree is **lazy-loaded** level by level to avoid fetching the entire asset hierarchy upfront:

```
Level 0: GET /zones?parent_id=null        → Root zones
Level 1: GET /zones?parent_id={zoneId}    → Child zones (max 2 levels)
Level 1: GET /systems?zone_id={zoneId}    → Systems in zone
Level 2: GET /sub-systems?system_id={sysId} → Sub-systems
Level 3: GET /service-points?parent_id={subSysId} → Nodes
```

Each level loads on **expand**. React Query caches each level independently.

### 10.2 Tree Node Component

```tsx
// layout/AssetTreeNode.tsx
interface TreeNodeProps {
  node: TreeItem;
  depth: number;
  onExpand: (id: string) => void;
  onSelect: (id: string, type: TabType) => void;
}

// Each node shows:
// - Expand/collapse chevron (if has children)
// - Icon (zone=🏢, system=⚙️, sub-system=🔧, node=📍)
// - Name
// - Safety flag badge (if applicable, fetched from asset flags)
// - Click → opens corresponding detail tab
```

### 10.3 Tree-Tab Integration

When a user clicks a tree node:
1. `useTreeStore.selectNode(id)` updates the selected highlight.
2. `useTabStore.openTab({ type: 'node-detail', title: node.name, params: { nodeId: id } })` opens or focuses the detail tab.

### 10.4 Collapse Behavior

The tree band collapses to a thin icon strip (`var(--tree-band-collapsed-width)`). A toggle button at the bottom of the band controls this. State is persisted in `useLayoutStore`.

---

## 11. Right AI Side-Band

### 11.1 Persistent Availability

The AI side-band is rendered in `AppShell` and is **always present** in the DOM (collapsed to a thin strip when closed). It is accessible from every tab.

### 11.2 Contextual Awareness

The AI panel's context updates based on the active tab:

| Active Tab | AI Context |
|---|---|
| Node Detail | `nodeId` set → RAG queries scoped to that node's manuals |
| Template Editor | "Generate Checklist" mode activated |
| Any other tab | General chat mode (no RAG scope, or last-used scope) |

```typescript
// When NodeDetailPage mounts:
useEffect(() => {
  useAIPanelStore.getState().setContext({ nodeId: params.nodeId });
  return () => useAIPanelStore.getState().setContext({});
}, [params.nodeId]);
```

### 11.3 AI Panel Modes

| Mode | Trigger | API Endpoint | UI |
|---|---|---|---|
| **RAG Chat** | Default when panel opens on a node | `POST /ai/chat` | Chat thread, input box, citations |
| **Checklist Generation** | "AI Generate" button in Template Editor | `POST /ai/checklist/generate` | Prompt input, draft preview table, approve button |
| **Manual Ingestion Status** | "Mark for AI ingestion" on node | `POST /ai/ingest` | Progress indicator |

### 11.4 Panel Layout

```
┌─────────────────────────┐
│  🤖 AI Assistant    [×] │
│  Context: Node PUMP-01  │
├─────────────────────────┤
│                         │
│  Chat Thread            │
│  ┌───────────────────┐  │
│  │ User: What is the │  │
│  │ torque spec?      │  │
│  └───────────────────┘  │
│  ┌───────────────────┐  │
│  │ AI: The torque    │  │
│  │ spec is 45 Nm...  │  │
│  │ 📄 manual.pdf p.12│  │
│  └───────────────────┘  │
│                         │
├─────────────────────────┤
│  [Type your question…]  │
│  [Send] [Clear] [Retry] │
└─────────────────────────┘
```

### 11.5 API Integration

```typescript
// api/endpoints/ai.ts
export const aiApi = {
  chat: (data: { message: string; node_id?: string; thread_id?: string }) =>
    apiClient.post<AIChatResponse>('/ai/chat', data),
  generateChecklist: (data: { prompt: string; template_id?: string }) =>
    apiClient.post<AIChecklistDraft>('/ai/checklist/generate', data),
  ingestDocument: (fileId: string) =>
    apiClient.post(`/ai/ingest/${fileId}`),
};
```

---

## 12. RTL/LTR Bi-Directional Support

### 12.1 Implementation

1. **HTML attribute**: `<html dir={direction}>` where `direction` is `'rtl'` or `'ltr'`.
2. **Tailwind config**: Enable logical properties plugin (built-in Tailwind v3.3+).
3. **CSS variables**: No directional values in CSS variables; use logical properties in component classes.
4. **Persistence**: User's preference stored in `localStorage` and `useLayoutStore`.
5. **Default**: Detected from `navigator.language` (Arabic/Hebrew → RTL, else LTR), overridable.

### 12.2 Testing

- Dedicated test suite in `tests/rtl/` that renders key components with `dir="rtl"` and asserts layout correctness.
- Visual regression tests in Storybook with RTL decorator.

---

## 13. Page-by-Page Component Architecture

### 13.1 Login Page (`pages/auth/LoginPage.tsx`)

**Layout**: Centered card on a branded background. No shell (outside `AppShell`).

| Element | Component | API | Validation |
|---|---|---|---|
| Email/Username input | `<Input type="text">` | — | Zod: email or non-empty string |
| Password input | `<SecureInput>` | — | Zod: min 1 char |
| Remember me | `<Checkbox>` | — | Boolean |
| Login button | `<Button variant="primary">` | `POST /auth/login` | — |
| Forgot password link | `<Link>` | — | Navigates to `/forgot-password` |
| Sign up link | `<Link>` | — | Navigates to `/signup` |

**Post-login flow**: Store access token → call `GET /auth/me` → populate auth context → navigate to `/` → `AppShell` mounts → open Dashboard tab.

### 13.2 Signup Page (`pages/auth/SignupPage.tsx`)

| Element | Component | API | Validation |
|---|---|---|---|
| Full name | `<Input>` | — | Zod: min 2 chars |
| Email | `<Input type="email">` | — | Zod: email format |
| Password | `<SecureInput>` | — | Zod: min 8, 1 upper, 1 number |
| Confirm password | `<SecureInput>` | — | Zod: must match password |
| Password policy hint | `<Text variant="muted">` | — | Static text |
| Create account button | `<Button>` | `POST /auth/signup` | — |

### 13.3 Email Verification Page (`pages/auth/EmailVerificationPage.tsx`)

| Element | Component | API |
|---|---|---|
| Prompt text | `<Text>` | — |
| Resend button | `<Button variant="secondary">` | `POST /auth/resend-verification` |

### 13.4 Forgot Password Page (`pages/auth/ForgotPasswordPage.tsx`)

| Element | Component | API |
|---|---|---|
| Email input | `<Input type="email">` | — |
| Send reset link button | `<Button>` | `POST /auth/forgot-password` |

### 13.5 Reset Password Page (`pages/auth/ResetPasswordPage.tsx`)

| Element | Component | API | Validation |
|---|---|---|---|
| New password | `<SecureInput>` | — | Same complexity as signup |
| Confirm password | `<SecureInput>` | — | Must match |
| Reset button | `<Button>` | `POST /auth/reset-password` | Token from URL query param |

### 13.6 Main Dashboard (`pages/dashboard/DashboardPage.tsx`)

**Layout**: Grid of widgets. Responsive: 1 column mobile, 2 tablet, 4 desktop.

| Element | Component | API Hook |
|---|---|---|
| User counters (New/Active WOs) | `<KPICard>` × 2 | `useDashboardCounters()` → `GET /workorders/counts` |
| KPI cards (overdue, open tickets, completion %) | `<KPICard>` × 3 | `useKPIs()` → `GET /reports/kpis` |
| WO status chart | `<ChartWrapper>` (Recharts PieChart) | `useWorkOrderStatusBreakdown()` → `GET /reports/kpis` |
| Safety flag incidents | `<ChartWrapper>` (Recharts BarChart) | `useSafetyFlagSummary()` → `GET /reports/kpis` |
| Recent notifications | `<NotificationList>` (compact) | `useNotifications({ limit: 5 })` → `GET /notifications` |

### 13.7 Zones Management (`pages/zones/ZoneListPage.tsx`)

| Element | Component | API Hook |
|---|---|---|
| Zones table | `<Table>` (TanStack) | `useZones(filters)` → `GET /zones` |
| Status filter | `<Select>` | Client-side filter param |
| Create zone button | `<Button>` → opens `<Modal>` with `<ZoneForm>` | `useCreateZone()` → `POST /zones` |
| Row action: Clone | `<Button icon="copy">` | `useCloneZone()` → `POST /zones/{id}/clone` |
| Row action: Open detail | Click row → `openTab('zone-detail', { zoneId })` | — |

### 13.8 Zone Detail & Cloning (`pages/zones/ZoneDetailPage.tsx`)

**Layout**: Top indicator cards row, then profile form, then hierarchy tree.

| Element | Component | API Hook |
|---|---|---|
| Systems count indicator | `<KPICard icon="⚙️">` | `useZoneStats(zoneId)` → `GET /zones/{id}/stats` |
| Nodes count indicator | `<KPICard icon="📍">` | Same |
| Attention required indicator | `<KPICard icon="⚠️" variant="warning">` | Same |
| Pending tickets indicator | `<KPICard icon="🎫">` | Same |
| Completed workflows (day/week) | `<KPICard icon="✅">` | Same |
| Zone profile form | `<ZoneForm>` | `useUpdateZone()` → `PATCH /zones/{id}` |
| Hierarchy tree | `<AssetTree>` (embedded, scoped) | `useZoneHierarchy(zoneId)` → `GET /zones/{id}/tree` |
| Clone button | `<Button>` → `<ConfirmDialog>` → `<CloneProgressIndicator>` | `useCloneZone()` → `POST /zones/{id}/clone` |

### 13.9 System Detail (`pages/systems/SystemDetailPage.tsx`)

| Element | Component | API Hook |
|---|---|---|
| Cross-zone engagements list | `<List>` with zone names | `useSystemZones(systemId)` → `GET /systems/{id}/zones` |
| "Switch to zone" button (per zone) | `<Button variant="ghost">` | `openTab('zone-detail', { zoneId })` |
| "Expand system" button | `<Button>` | Toggles sub-system/node list below |
| Sub-systems/nodes list | `<Table>` | `useSubSystems(systemId)` → `GET /sub-systems?system_id=` |
| System profile form | `<SystemForm>` | `useUpdateSystem()` → `PATCH /systems/{id}` |
| Zone links multi-select | `<MultiSelect>` | `useUpdateSystemZones()` → `PUT /systems/{id}/zones` |

### 13.10 Node Detail (`pages/nodes/NodeDetailPage.tsx`)

**Layout**: Top status badges row, action buttons row, then tabbed content.

| Element | Component | API Hook |
|---|---|---|
| Lifecycle status badge | `<StatusBadge>` (Active/Inactive/Decommissioned) | From `useNode(nodeId)` → `GET /service-points/{id}` |
| Hours since last action badge | `<Badge variant="info">` | Computed from `last_action_at` in node data |
| Critical notifications badge | `<Badge variant="critical" pulse>` | `useNodeAlerts(nodeId)` → `GET /service-points/{id}/alerts` |
| "See ticket history" button | `<Button>` | `openTab('ticket-list', { filter: { nodeId } })` |
| "See maint. history" button | `<Button>` | `openTab('wo-list', { filter: { nodeId } })` |
| "See manuals" button | `<Button>` | Scrolls to / opens Manuals sub-tab |
| "View node cycles" button | `<Button>` | `openTab('cycles', { filter: { nodeId } })` |
| **Tab: Profile** | `<NodeForm>` | `useUpdateNode()` → `PATCH /service-points/{id}` |
| **Tab: Counters** | `<CounterDisplay>` + `<Input>` + Reset button | `useLogCounter()` → `POST /service-points/{id}/counters/log`; `useResetCounter()` → `POST /service-points/{id}/counters/reset` |
| **Tab: Manuals** | `<FileUploader>` + file list | `useUploadFile()` → `POST /files`; "Mark for AI ingestion" button → `POST /ai/ingest/{fileId}` |
| **Tab: Safety** | `<Toggle>` per flag (HOT_INSPECT, PAUSE, STOP) | `useSetSafetyFlag()` → `POST /service-points/{id}/safety-flag` |

### 13.11 QR Scanner (`pages/qr/QRScannerPage.tsx`)

| Element | Component | API Hook |
|---|---|---|
| Camera viewfinder | `<Html5QrcodeScanner>` (html5-qrcode lib) | — |
| Manual code entry | `<Input>` + `<Button>` | `useResolveQR()` → `GET /qr/resolve/{code}` |
| Resolved node data | `<NodeSummaryCard>` | Renders result, button to open node detail tab |

### 13.12 Work Orders List (`pages/workorders/WorkOrderListPage.tsx`)

| Element | Component | API Hook |
|---|---|---|
| WO table | `<Table>` with columns: Code, Status, Asset, Deadline, Flags | `useWorkOrders(filters)` → `GET /workorders` |
| Role-based filter | Auto-applied: Maintenance sees assigned/pool; Manager sees all | Filter params based on `useAuthContext().role` |
| Overdue badge | `<Badge variant="critical">` on rows past deadline | Computed client-side from `deadline` |
| Row click | Opens `wo-exec` tab | `openTab('wo-exec', { woId })` |

### 13.13 Work Order Execution (`pages/workorders/WorkOrderExecutionPage.tsx`)

| Element | Component | API Hook |
|---|---|---|
| WO header | `<Card>` with code, asset, deadline, safety flags prominently displayed | `useWorkOrder(woId)` → `GET /workorders/{id}` |
| Work items list | `<WorkItemList>` — each item shows: activity #, predecessor status, description, measurement input | From WO snapshot data |
| Measurement input per item | `<MeasurementInput>` (renders Numeric/Text/Boolean based on item type) | — |
| Signature pad | `<SignaturePad>` (react-signature-canvas) | — |
| Snooze button | `<Button>` → `<Modal>` with duration selector (1h/6h/12h/1d/3d/6d) + mandatory reason `<Input>` | `useSnoozeWorkOrder()` → `POST /workorders/{id}/snooze` |
| Reject button | `<Button variant="danger">` → `<Modal>` with mandatory reason | `useRejectWorkOrder()` → `POST /workorders/{id}/reject` |
| Complete button | `<Button variant="primary">` → `<ConfirmDialog>` | `useCompleteWorkOrder()` → `POST /workorders/{id}/complete` |

### 13.14 Workflows & Checklists List (`pages/templates/TemplateListPage.tsx`)

| Element | Component | API Hook |
|---|---|---|
| Templates table | `<Table>` with columns: Code, Name, Type (Workflow/Checklist), Items count | `useTemplates(filters)` → `GET /templates` |
| Item-level search | `<SearchInput>` | Server-side: `GET /templates?search=` |
| Launch workflow now button | `<Button icon="play">` per row → `<ConfirmDialog>` | `useLaunchWorkflow()` → `POST /templates/{id}/launch` |
| Create button | `<Button>` → opens `template-editor` tab (new) | `openTab('template-editor', { templateId: 'new' })` |
| Row click | Opens `template-editor` tab | `openTab('template-editor', { templateId })` |

### 13.15 Cycles Management (`pages/cycles/CyclesPage.tsx`)

| Element | Component | API Hook |
|---|---|---|
| Cycles table | `<Table>` with columns: Name, Target Entity, Triggers, Launch Mode, Status | `useCycles(filters)` → `GET /cycles` |
| Reset cycle timer button | `<Button icon="refresh">` per row → `<ConfirmDialog>` | `useResetCycle()` → `POST /cycles/{id}/reset` |
| Pause/Resume cycle button | `<Toggle>` per row | `usePauseCycle()` → `POST /cycles/{id}/pause`; `useResumeCycle()` → `POST /cycles/{id}/resume` |
| Create cycle button | `<Button>` → `<Modal>` with `<CycleForm>` | `useCreateCycle()` → `POST /cycles` |

**CycleForm sub-components:**
- Target entity selector (Zone/System/Node picker using asset tree data)
- Template selector (dropdown of workflows/checklists)
- Trigger configuration: `<CycleTriggerConfig>` — multi-select of Calendar/Cron, Operating Hours, Operation Count with respective input fields
- Launch mode toggle: Automatic / Manual

### 13.16 Checklist/Workflow Editor (`pages/templates/TemplateEditorPage.tsx`)

| Element | Component | API Hook |
|---|---|---|
| Template metadata form | `<Input>` for name, description, code (auto-generated, read-only for existing) | `useUpdateTemplate()` → `PATCH /templates/{id}` |
| Work items list | Drag-sortable list of `<TemplateItemRow>` | Each row: activity #, predecessor dropdown, description, measurement type, unit, threshold |
| Add item button | `<Button>` | Appends empty row to local state |
| AI Generate button | `<Button icon="sparkles">` | Triggers AI panel to switch to checklist generation mode |
| AI Draft Preview | `<AIDraftPreview>` (table of generated items) | Renders response from `POST /ai/checklist/generate` |
| Approve/Save AI Draft | `<Button>` | Merges AI items into the editor's item list |
| Save button | `<Button variant="primary">` | `useSaveTemplate()` → `PUT /templates/{id}` |

### 13.17 Repair Tickets List (`pages/tickets/TicketListPage.tsx`)

| Element | Component | API Hook |
|---|---|---|
| Tickets table | `<Table>` with columns: Code, Priority, Status, Asset, Assignee | `useTickets(filters)` → `GET /tickets` |
| Create ticket button | `<Button>` → `<Modal>` with form | `useCreateTicket()` → `POST /tickets`; Blocked if org payment overdue (server returns 403) |
| Maintenance pool filter | `<Toggle>` "Show unassigned only" | Filter param: `status=OPEN&assigned_to=null` |
| Row click | Opens `ticket-detail` tab | `openTab('ticket-detail', { ticketId })` |

### 13.18 Ticket Detail & Feedback Flow (`pages/tickets/TicketDetailPage.tsx`)

| Element | Component | API Hook |
|---|---|---|
| Ticket header | `<Card>` with code, priority badge, status, asset, issuer | `useTicket(ticketId)` → `GET /tickets/{id}` |
| Claim button | `<Button>` (visible only to Maintenance, only when status=OPEN) | `useClaimTicket()` → `POST /tickets/{id}/claim` |
| Report form | `<TicketReportForm>` (work performed, findings, attachments) | `useSubmitReport()` → `POST /tickets/{id}/report` |
| Feedback form | `<FeedbackForm>` (issuer review, feedback text) | `useSubmitFeedback()` → `POST /tickets/{id}/feedback` |
| Loop counter warning | `<Alert variant="warning">` | Shows when `loop_count >= 2` (approaching max 3) |
| Escalate button | `<Button variant="danger">` | `useEscalateTicket()` → `POST /tickets/{id}/escalate` |
| Manager decision panel | `<RadioGroup>` (FORCE_CLOSE / REQUIRE_NEW_TICKET / MANDATE_ACTION) + `<Button>` | `useManagerDecide()` → `POST /tickets/{id}/decide` |
| History timeline | `<Timeline>` component showing all reports, feedbacks, escalations | From ticket detail response |

### 13.19 Reports & KPIs (`pages/reports/ReportsPage.tsx`)

| Element | Component | API Hook |
|---|---|---|
| KPI widgets grid | `<KPICard>` × N | `useKPIs(filters)` → `GET /reports/kpis` |
| Date range filter | `<DatePicker range>` | Filter params |
| Asset filter | `<MultiSelect>` (zones/systems) | Filter params |
| Export button | `<ExportButton>` → triggers download | `useExportReport()` → `POST /reports/export` (returns job ID) |
| Export history list | `<Table>` with past exports and download links | `useExportHistory()` → `GET /reports/exports` |

### 13.20 User Profile (`pages/settings/UserProfilePage.tsx`)

| Element | Component | API Hook |
|---|---|---|
| Personal details form | `<Input>` for name, phone 1, phone 2, employee ID, timezone `<Select>` | `useUpdateProfile()` → `PATCH /auth/me` |
| Change password button | `<Button>` → `<Modal>` with `<PasswordForm>` | `useChangePassword()` → `POST /auth/change-password` |
| RTL/LTR toggle | `<Toggle>` | Updates `useLayoutStore`, persists to `localStorage` |

### 13.21 Notifications Center (`pages/notifications/NotificationsPage.tsx`)

| Element | Component | API Hook |
|---|---|---|
| Notification list | `<List>` with icon, message, timestamp, read/unread styling | `useNotifications()` → `GET /notifications` |
| Mark as read | Click or `<Button>` per item | `useMarkRead()` → `PATCH /notifications/{id}/read` |
| Deep navigation | Click notification → opens relevant tab | Parses `notification.entity_type` and `entity_id` to call `openTab()` |

### 13.22 Organization Settings & Team (`pages/settings/OrgSettingsPage.tsx`)

| Element | Component | API Hook |
|---|---|---|
| Org profile form | `<Input>` for name, logo upload, contact, timezone, custom fields | `useUpdateOrg()` → `PATCH /organizations/me` |
| Subscription tier display | `<Card>` showing tier name, active nodes / limit | `useOrgTier()` → `GET /organizations/tier` |
| Team members table | `<Table>` with columns: Name, Email, Role, Status | `useTeamMembers()` → `GET /organizations/members` |
| Create new user button | `<Button>` → `<Modal>` with `<UserInviteForm>` (email input) | `useInviteUser()` → `POST /organizations/invitations` |
| Change role action | `<Select>` dropdown per row | `useChangeRole()` → `PATCH /organizations/members/{id}` |
| Remove user button | `<Button variant="danger">` → `<ConfirmDialog>` (validates no locks) | `useRemoveUser()` → `DELETE /organizations/members/{id}` |
| Payment overdue alert | `<Alert variant="critical">` | Shown when `useOrgTier()` returns `payment_overdue: true` |

### 13.23 Audit Log (`pages/audit/AuditLogPage.tsx`)

| Element | Component | API Hook |
|---|---|---|
| Audit events table | `<Table>` with columns: Timestamp, Actor, Action, Entity, Entity ID | `useAuditLog(filters)` → `GET /audit` |
| Filters | `<Select>` for actor, entity type; `<DatePicker>` for date range | Filter params |
| State diff detail | `<Modal>` showing JSON diff (previous vs new state) | From row data or `GET /audit/{id}` |

---

## 14. Role-Based UI Visibility

### 14.1 Role Summary

| Role | Key Capabilities |
|---|---|
| **Operator** | View assets, create tickets, view own WOs, AI chat |
| **Maintenance** | Execute WOs, claim tickets, submit reports, log counters, AI chat |
| **Manager** | Full CRUD on assets/cycles/templates, clone zones, safety flags, team management, reports, audit, AI generate |
| **Reporter** | View all WOs/tickets, reports, export, AI chat |
| **SysAdmin** | Audit log, system-level operations |

### 14.2 Implementation Points

| UI Area | Role Logic |
|---|---|
| Left Asset Tree | All roles see the tree; Manager sees "Clone" context action |
| WO List | Maintenance: filter to assigned + pool; Manager/Reporter: all org WOs |
| WO Execution | Only Maintenance sees "Complete", "Snooze", "Reject" buttons |
| Ticket List | Operator/Manager see "Create Ticket"; Maintenance sees "Claim" on OPEN tickets |
| Ticket Detail | "Claim" visible only to Maintenance; "Submit Report" only to assigned Maintenance; "Feedback" only to issuer; "Manager Decision" only to Manager |
| Node Detail | "Safety Flag" toggles visible only to Manager/Maintenance |
| Template Editor | Only Manager can edit/create; others read-only |
| Cycles | Only Manager can create/reset/pause |
| Org Settings | Only Manager can access |
| Audit Log | Only Manager/SysAdmin can access |
| AI Generate Checklist | Only Manager sees the "AI Generate" button in template editor |
| AI Chat | All roles can use |

---

## 15. Error Handling & UX Patterns

### 15.1 Error Envelope

The server returns: `{ error_code: string, message: string, details?: any }`

The UI parses this in the Axios interceptor and surfaces it via:
- **Toast notifications** for transient errors (network, 500)
- **Inline form errors** for validation errors (422, mapped to field names via `details`)
- **Full-page error states** for 403 (permission denied) or 404 (entity not found)

### 15.2 Loading States

- **Skeleton loaders** for initial page loads (tab content area)
- **Spinner overlays** for mutations (buttons show `loading` state)
- **Optimistic updates** where safe (e.g., marking notification as read)

### 15.3 Empty States

Every list/table has an `<EmptyState>` component with an illustration, message, and optional action button (e.g., "No work orders found. Create a cycle to generate work orders.").

### 15.4 Confirmation Dialogs

Destructive actions (delete, clone, complete WO, remove user) require `<ConfirmDialog>` with:
- Clear description of the action
- Required typed confirmation for critical actions (e.g., type "DELETE" to confirm)
- Cancel/Confirm buttons

---

## 16. Testing Strategy

### 16.1 Test Pyramid

| Level | Tool | Scope | Count Target |
|---|---|---|---|
| Unit | Vitest | Pure functions (formatters, validators, permissions) | ~100 |
| Component | Vitest + Testing Library | Individual components with mocked props | ~150 |
| Integration | Vitest + Testing Library + MSW | Page components with mocked API | ~50 |
| E2E | Playwright | Full user flows (login → create WO → execute) | ~20 |
| Visual | Storybook + Chromatic | Component appearance, RTL rendering | All components |

### 16.2 Key Test Scenarios

- **Auth flow**: Login → token stored → 401 triggers refresh → logout clears state
- **Tab system**: Open tab → focus existing → close → pin → reorder
- **Asset tree**: Lazy load levels → expand/collapse → click opens tab
- **RBAC**: Render pages with each role → assert visibility of restricted elements
- **RTL**: Render key pages with `dir="rtl"` → assert layout correctness
- **Form validation**: Submit invalid data → assert inline errors match Zod schemas
- **AI panel**: Open → context updates with active tab → send message → render response with citations

### 16.3 MSW Mock Setup

```typescript
// test/mocks/handlers.ts
import { http, HttpResponse } from 'msw';

export const handlers = [
  http.get('*/api/v1/auth/me', () => {
    return HttpResponse.json({ id: 'u1', email: 'test@test.com', role: 'Manager' });
  }),
  http.get('*/api/v1/zones', () => {
    return HttpResponse.json({ items: [...], page: 1, total: 10 });
  }),
  // ... one handler per endpoint
];
```

---

## 17. Build, CI/CD & Deployment

### 17.1 Build Configuration

```typescript
// vite.config.ts
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  build: {
    target: 'es2020',
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom'],
          query: ['@tanstack/react-query'],
          ui: ['@tanstack/react-table', 'recharts'],
        },
      },
    },
  },
});
```

### 17.2 Deployment

- The UI is built to `dist/` and served as a **static site** from a separate server/CDN (not from the FastAPI server, as specified in `Server_architecture.md`: "Serves no static files — UI is hosted elsewhere").
- Nginx or Cloudflare serves the SPA with fallback to `index.html` for client-side routing.
- The SPA communicates with the API server via the configured `VITE_API_BASE_URL`.

### 17.3 CI/CD Pipeline (GitHub Actions)

```yaml
steps:
  - checkout
  - setup node 20
  - install dependencies
  - lint (eslint)
  - type check (tsc --noEmit)
  - unit + component tests (vitest)
  - build (vite build)
  - e2e tests (playwright, against staging API)
  - deploy to staging (S3/Cloudflare Pages)
  - manual approval → deploy to production
```

---

## 18. Implementation Roadmap (Wave Plan)

### Wave 0: Foundation (Week 1–2)
- [ ] Initialize Vite + React + TypeScript project
- [ ] Configure Tailwind CSS with logical properties
- [ ] Set up ESLint, Prettier, Vitest, MSW
- [ ] Build design system primitives (`components/ui/*`)
- [ ] Implement `lib/constants.ts`, `lib/permissions.ts`, `lib/cn.ts`
- [ ] Set up Axios client with interceptors
- [ ] Generate TypeScript types from server OpenAPI spec

### Wave 1: Auth & Shell (Week 3–4)
- [ ] Implement `AuthProvider`, `tokenManager`, `RequireAuth`, `RequireRole`
- [ ] Build auth pages: Login, Signup, Email Verification, Forgot/Reset Password
- [ ] Build `AppShell` layout skeleton (Header, TabBar, WorkspaceArea)
- [ ] Implement `useTabStore` and `TabContent` router
- [ ] Implement `useLayoutStore` with RTL/LTR toggle
- [ ] Build Header component with notification bell, user menu, RTL toggle

### Wave 2: Asset Tree & Core Pages (Week 5–7)
- [ ] Implement `useTreeStore` and `AssetTree` / `AssetTreeNode` with lazy loading
- [ ] Build Dashboard page with KPI cards and charts
- [ ] Build Zone List and Zone Detail pages (with indicator cards)
- [ ] Build System Detail page (with cross-zone list)
- [ ] Build Node Detail page (with status badges, action buttons, tabbed content)
- [ ] Build QR Scanner page

### Wave 3: Maintenance Operations (Week 8–10)
- [ ] Build Work Order List page
- [ ] Build Work Order Execution page (items, measurements, signature, snooze, complete)
- [ ] Build Template List page (with "Launch now" button)
- [ ] Build Template Editor page (item rows, drag-sort)
- [ ] Build Cycles Management page (with reset/pause buttons)

### Wave 4: Tickets & Reports (Week 11–12)
- [ ] Build Ticket List page
- [ ] Build Ticket Detail page (claim, report, feedback, escalation, manager decision)
- [ ] Build Reports & KPIs page (filters, charts, export)
- [ ] Build Notifications Center page

### Wave 5: AI Integration (Week 13–14)
- [ ] Implement `useAIPanelStore` and `AISideBand` component
- [ ] Build RAG Chat mode (thread, input, citations)
- [ ] Build Checklist Generation mode (prompt, draft preview, approve)
- [ ] Wire AI context to Node Detail and Template Editor pages
- [ ] Build "Mark for AI ingestion" flow in Node Manuals tab

### Wave 6: Admin & Polish (Week 15–16)
- [ ] Build Organization Settings & Team page (create user, change role, remove user)
- [ ] Build User Profile page
- [ ] Build Audit Log page
- [ ] Implement global search (Cmd+K)
- [ ] RTL/LTR full audit and fix pass
- [ ] Role-based visibility audit across all pages
- [ ] Error handling polish (toasts, empty states, loading skeletons)
- [ ] E2E test suite with Playwright
- [ ] Storybook component documentation
- [ ] Performance audit (bundle size, lazy loading, React Query tuning)

---
