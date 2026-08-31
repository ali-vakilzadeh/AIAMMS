import { UserRole, PermissionAction, ResourceType } from './constants';

/**
 * Role hierarchy - higher number means more permissions
 */
const ROLE_HIERARCHY: Record<UserRole, number> = {
  [UserRole.VIEWER]: 1,
  [UserRole.OPERATOR]: 2,
  [UserRole.TECHNICIAN]: 3,
  [UserRole.SUPERVISOR]: 4,
  [UserRole.MANAGER]: 5,
  [UserRole.ADMIN]: 6,
};

/**
 * Default permissions matrix by role and resource type
 * This defines which actions each role can perform on each resource type
 */
const DEFAULT_PERMISSIONS: Record<
  UserRole,
  Partial<Record<ResourceType, PermissionAction[]>>
> = {
  [UserRole.VIEWER]: {
    [ResourceType.ASSET]: [PermissionAction.READ],
    [ResourceType.WORK_ORDER]: [PermissionAction.READ],
    [ResourceType.TEMPLATE]: [PermissionAction.READ],
    [ResourceType.CYCLE]: [PermissionAction.READ],
    [ResourceType.TICKET]: [PermissionAction.READ],
    [ResourceType.REPORT]: [PermissionAction.READ],
  },
  [UserRole.OPERATOR]: {
    [ResourceType.ASSET]: [PermissionAction.READ],
    [ResourceType.WORK_ORDER]: [PermissionAction.READ, PermissionAction.EXECUTE],
    [ResourceType.TEMPLATE]: [PermissionAction.READ],
    [ResourceType.CYCLE]: [PermissionAction.READ],
    [ResourceType.TICKET]: [
      PermissionAction.READ,
      PermissionAction.CREATE,
      PermissionAction.UPDATE,
    ],
    [ResourceType.REPORT]: [PermissionAction.READ],
  },
  [UserRole.TECHNICIAN]: {
    [ResourceType.ASSET]: [PermissionAction.READ, PermissionAction.UPDATE],
    [ResourceType.WORK_ORDER]: [
      PermissionAction.READ,
      PermissionAction.EXECUTE,
      PermissionAction.UPDATE,
    ],
    [ResourceType.TEMPLATE]: [PermissionAction.READ],
    [ResourceType.CYCLE]: [PermissionAction.READ],
    [ResourceType.TICKET]: [
      PermissionAction.READ,
      PermissionAction.CREATE,
      PermissionAction.UPDATE,
    ],
    [ResourceType.REPORT]: [PermissionAction.READ],
  },
  [UserRole.SUPERVISOR]: {
    [ResourceType.ASSET]: [
      PermissionAction.READ,
      PermissionAction.UPDATE,
      PermissionAction.CREATE,
    ],
    [ResourceType.WORK_ORDER]: [
      PermissionAction.READ,
      PermissionAction.CREATE,
      PermissionAction.UPDATE,
      PermissionAction.APPROVE,
    ],
    [ResourceType.TEMPLATE]: [
      PermissionAction.READ,
      PermissionAction.CREATE,
      PermissionAction.UPDATE,
    ],
    [ResourceType.CYCLE]: [
      PermissionAction.READ,
      PermissionAction.CREATE,
      PermissionAction.UPDATE,
    ],
    [ResourceType.TICKET]: [
      PermissionAction.READ,
      PermissionAction.CREATE,
      PermissionAction.UPDATE,
      PermissionAction.APPROVE,
    ],
    [ResourceType.REPORT]: [PermissionAction.READ, PermissionAction.CREATE],
  },
  [UserRole.MANAGER]: {
    [ResourceType.ASSET]: [
      PermissionAction.READ,
      PermissionAction.UPDATE,
      PermissionAction.CREATE,
      PermissionAction.DELETE,
    ],
    [ResourceType.WORK_ORDER]: [
      PermissionAction.READ,
      PermissionAction.CREATE,
      PermissionAction.UPDATE,
      PermissionAction.DELETE,
      PermissionAction.APPROVE,
    ],
    [ResourceType.TEMPLATE]: [
      PermissionAction.READ,
      PermissionAction.CREATE,
      PermissionAction.UPDATE,
      PermissionAction.DELETE,
    ],
    [ResourceType.CYCLE]: [
      PermissionAction.READ,
      PermissionAction.CREATE,
      PermissionAction.UPDATE,
      PermissionAction.DELETE,
    ],
    [ResourceType.TICKET]: [
      PermissionAction.READ,
      PermissionAction.CREATE,
      PermissionAction.UPDATE,
      PermissionAction.DELETE,
      PermissionAction.APPROVE,
    ],
    [ResourceType.REPORT]: [
      PermissionAction.READ,
      PermissionAction.CREATE,
      PermissionAction.DELETE,
    ],
    [ResourceType.USER]: [
      PermissionAction.READ,
      PermissionAction.CREATE,
      PermissionAction.UPDATE,
    ],
  },
  [UserRole.ADMIN]: {
    [ResourceType.ASSET]: [
      PermissionAction.READ,
      PermissionAction.CREATE,
      PermissionAction.UPDATE,
      PermissionAction.DELETE,
    ],
    [ResourceType.WORK_ORDER]: [
      PermissionAction.READ,
      PermissionAction.CREATE,
      PermissionAction.UPDATE,
      PermissionAction.DELETE,
      PermissionAction.APPROVE,
    ],
    [ResourceType.TEMPLATE]: [
      PermissionAction.READ,
      PermissionAction.CREATE,
      PermissionAction.UPDATE,
      PermissionAction.DELETE,
    ],
    [ResourceType.CYCLE]: [
      PermissionAction.READ,
      PermissionAction.CREATE,
      PermissionAction.UPDATE,
      PermissionAction.DELETE,
    ],
    [ResourceType.TICKET]: [
      PermissionAction.READ,
      PermissionAction.CREATE,
      PermissionAction.UPDATE,
      PermissionAction.DELETE,
      PermissionAction.APPROVE,
    ],
    [ResourceType.REPORT]: [
      PermissionAction.READ,
      PermissionAction.CREATE,
      PermissionAction.DELETE,
    ],
    [ResourceType.USER]: [
      PermissionAction.READ,
      PermissionAction.CREATE,
      PermissionAction.UPDATE,
      PermissionAction.DELETE,
    ],
    [ResourceType.ORGANIZATION]: [
      PermissionAction.READ,
      PermissionAction.CREATE,
      PermissionAction.UPDATE,
      PermissionAction.DELETE,
    ],
  },
};

/**
 * Check if a user role has a specific permission
 */
export function hasPermission(
  userRole: UserRole,
  resourceType: ResourceType,
  action: PermissionAction
): boolean {
  const rolePermissions = DEFAULT_PERMISSIONS[userRole];
  if (!rolePermissions) return false;

  const resourcePermissions = rolePermissions[resourceType];
  if (!resourcePermissions) return false;

  return resourcePermissions.includes(action);
}

/**
 * Check if a user role has all permissions for a resource
 */
export function hasAllPermissions(
  userRole: UserRole,
  resourceType: ResourceType,
  actions: PermissionAction[]
): boolean {
  return actions.every((action) => hasPermission(userRole, resourceType, action));
}

/**
 * Check if a user role has at least one permission for a resource
 */
export function hasAnyPermission(
  userRole: UserRole,
  resourceType: ResourceType,
  actions: PermissionAction[]
): boolean {
  return actions.some((action) => hasPermission(userRole, resourceType, action));
}

/**
 * Get all permissions for a role
 */
export function getRolePermissions(userRole: UserRole) {
  return DEFAULT_PERMISSIONS[userRole] || {};
}

/**
 * Check if a role is equal or higher than another role
 */
export function isRoleAtLeast(
  userRole: UserRole,
  requiredRole: UserRole
): boolean {
  return ROLE_HIERARCHY[userRole] >= ROLE_HIERARCHY[requiredRole];
}

/**
 * Check if a role is higher than another role
 */
export function isRoleHigherThan(
  userRole: UserRole,
  comparedRole: UserRole
): boolean {
  return ROLE_HIERARCHY[userRole] > ROLE_HIERARCHY[comparedRole];
}
