/**
 * User roles in the CMMS system
 */
export enum UserRole {
  ADMIN = 'admin',
  MANAGER = 'manager',
  SUPERVISOR = 'supervisor',
  TECHNICIAN = 'technician',
  OPERATOR = 'operator',
  VIEWER = 'viewer',
}

/**
 * Asset status types
 */
export enum AssetStatus {
  ONLINE = 'online',
  OFFLINE = 'offline',
  MAINTENANCE = 'maintenance',
  FAULTY = 'faulty',
  DECOMMISSIONED = 'decommissioned',
}

/**
 * Work order status types
 */
export enum WorkOrderStatus {
  DRAFT = 'draft',
  PENDING = 'pending',
  ASSIGNED = 'assigned',
  IN_PROGRESS = 'in_progress',
  ON_HOLD = 'on_hold',
  COMPLETED = 'completed',
  CANCELLED = 'cancelled',
  OVERDUE = 'overdue',
}

/**
 * Priority levels
 */
export enum Priority {
  LOW = 'low',
  MEDIUM = 'medium',
  HIGH = 'high',
  URGENT = 'urgent',
}

/**
 * Safety levels
 */
export enum SafetyLevel {
  LOW = 'low',
  MEDIUM = 'medium',
  HIGH = 'high',
  CRITICAL = 'critical',
}

/**
 * Ticket status types
 */
export enum TicketStatus {
  OPEN = 'open',
  IN_REVIEW = 'in_review',
  ESCALATED = 'escalated',
  RESOLVED = 'resolved',
  CLOSED = 'closed',
}

/**
 * Cycle status types
 */
export enum CycleStatus {
  ACTIVE = 'active',
  PAUSED = 'paused',
  COMPLETED = 'completed',
  EXPIRED = 'expired',
}

/**
 * Notification types
 */
export enum NotificationType {
  INFO = 'info',
  WARNING = 'warning',
  ERROR = 'error',
  SUCCESS = 'success',
}

/**
 * Permission actions
 */
export enum PermissionAction {
  CREATE = 'create',
  READ = 'read',
  UPDATE = 'update',
  DELETE = 'delete',
  EXECUTE = 'execute',
  APPROVE = 'approve',
}

/**
 * Resource types for permissions
 */
export enum ResourceType {
  ASSET = 'asset',
  WORK_ORDER = 'work_order',
  TEMPLATE = 'template',
  CYCLE = 'cycle',
  TICKET = 'ticket',
  REPORT = 'report',
  USER = 'user',
  ORGANIZATION = 'organization',
}

// Type interfaces
export interface User {
  id: string;
  email: string;
  firstName: string;
  lastName: string;
  role: UserRole;
  organizationId: string;
  avatarUrl?: string;
  createdAt: string;
  updatedAt: string;
}

export interface AuthTokens {
  accessToken: string;
  refreshToken: string;
  expiresAt: number;
}

export interface LoginCredentials {
  email: string;
  password: string;
  rememberMe?: boolean;
}

export interface SignupCredentials {
  email: string;
  password: string;
  firstName: string;
  lastName: string;
  organizationName: string;
}

export interface ApiResponse<T> {
  data: T;
  message?: string;
  status: number;
}

export interface ApiError {
  message: string;
  code: string;
  details?: Record<string, string[]>;
  status: number;
}

export interface Asset {
  id: string;
  name: string;
  type: 'zone' | 'system' | 'node';
  parentId?: string;
  status: AssetStatus;
  metadata?: Record<string, unknown>;
  childrenCount?: number;
}

export interface Zone extends Asset {
  type: 'zone';
  description?: string;
  location?: string;
}

export interface System extends Asset {
  type: 'system';
  zoneId: string;
  crossZoneEngagements?: string[];
}

export interface Node extends Asset {
  type: 'node';
  systemId: string;
  zoneId: string;
  safetyLevel?: SafetyLevel;
  counters?: Record<string, number>;
}

export interface WorkOrder {
  id: string;
  title: string;
  description?: string;
  status: WorkOrderStatus;
  priority: Priority;
  assetId: string;
  assignedTo?: string;
  createdBy: string;
  dueDate?: string;
  completedAt?: string;
  templateId?: string;
  cycleId?: string;
}

export interface Template {
  id: string;
  name: string;
  description?: string;
  items: TemplateItem[];
  assetType: 'zone' | 'system' | 'node';
  createdBy: string;
  createdAt: string;
  updatedAt: string;
}

export interface TemplateItem {
  id: string;
  order: number;
  task: string;
  category?: string;
  required?: boolean;
  measurementType?: 'text' | 'number' | 'boolean' | 'photo';
  measurementUnit?: string;
  acceptableRange?: { min: number; max: number };
}

export interface Cycle {
  id: string;
  name: string;
  templateId: string;
  assetId: string;
  status: CycleStatus;
  frequency: number;
  frequencyUnit: 'hours' | 'days' | 'weeks' | 'months';
  lastExecution?: string;
  nextExecution?: string;
  triggerConfig?: TriggerConfig;
}

export interface TriggerConfig {
  type: 'time' | 'counter' | 'manual';
  counterName?: string;
  counterThreshold?: number;
}

export interface Ticket {
  id: string;
  title: string;
  description: string;
  status: TicketStatus;
  priority: Priority;
  assetId?: string;
  workOrderId?: string;
  reportedBy: string;
  assignedTo?: string;
  escalatedTo?: string;
  feedback?: TicketFeedback;
  createdAt: string;
  updatedAt: string;
}

export interface TicketFeedback {
  rating: number;
  comment?: string;
  submittedAt: string;
}

export interface Notification {
  id: string;
  type: NotificationType;
  title: string;
  message: string;
  isRead: boolean;
  relatedEntityId?: string;
  relatedEntityType?: string;
  createdAt: string;
}

export interface AIChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  citations?: AICitation[];
  timestamp: string;
}

export interface AICitation {
  source: string;
  url?: string;
  excerpt?: string;
}

export interface AIChatRequest {
  messages: AIChatMessage[];
  context?: AIContext;
}

export interface AIContext {
  currentPage?: string;
  selectedAsset?: Asset;
  userRole?: string;
}

export interface DashboardKPI {
  id: string;
  label: string;
  value: number | string;
  change?: number;
  changeType?: 'increase' | 'decrease';
  status?: AssetStatus;
}
