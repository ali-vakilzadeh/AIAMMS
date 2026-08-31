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
 * Role hierarchy levels (higher number = more permissions)
 */
export const ROLE_HIERARCHY: Record<UserRole, number> = {
  [UserRole.ADMIN]: 6,
  [UserRole.MANAGER]: 5,
  [UserRole.SUPERVISOR]: 4,
  [UserRole.TECHNICIAN]: 3,
  [UserRole.OPERATOR]: 2,
  [UserRole.VIEWER]: 1,
};

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
