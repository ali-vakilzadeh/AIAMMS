import React, { ReactNode } from 'react';
import { useAuth } from './AuthProvider';
import { UserRole, ROLE_HIERARCHY } from '@/lib/constants';

interface RequireRoleProps {
  children: ReactNode;
  allowedRoles: UserRole[];
  fallback?: ReactNode;
}

/**
 * RequireRole Component
 * Protects routes that require specific user roles.
 * Shows fallback or redirects if user doesn't have required role.
 */
export const RequireRole: React.FC<RequireRoleProps> = ({ 
  children, 
  allowedRoles, 
  fallback = null 
}) => {
  const { user, isLoading } = useAuth();

  // Show loading state while checking auth
  if (isLoading) {
    return fallback || (
      <div className="flex h-screen w-full items-center justify-center">
        <div className="animate-spin rounded-full border-4 border-primary border-t-transparent h-12 w-12" />
      </div>
    );
  }

  // Check if user has required role
  if (!user || !hasRequiredRole(user.role, allowedRoles)) {
    return fallback || (
      <div className="flex h-screen w-full flex-col items-center justify-center gap-4">
        <h1 className="text-2xl font-bold text-destructive">Access Denied</h1>
        <p className="text-muted-foreground">
          You don't have permission to access this page.
        </p>
        <button
          onClick={() => window.history.back()}
          className="btn btn-primary"
        >
          Go Back
        </button>
      </div>
    );
  }

  return <>{children}</>;
};

/**
 * Check if user has at least one of the required roles
 * Uses role hierarchy to determine permissions
 */
function hasRequiredRole(userRole: UserRole, allowedRoles: UserRole[]): boolean {
  // Get the highest role level the user has
  const userLevel = ROLE_HIERARCHY[userRole] ?? 0;
  
  // Check if user has any of the allowed roles or higher
  return allowedRoles.some((role) => {
    const requiredLevel = ROLE_HIERARCHY[role] ?? 0;
    return userLevel >= requiredLevel;
  });
}

/**
 * Utility function to check if a user has a specific role
 */
export function hasRole(userRole: UserRole, requiredRole: UserRole): boolean {
  const userLevel = ROLE_HIERARCHY[userRole] ?? 0;
  const requiredLevel = ROLE_HIERARCHY[requiredRole] ?? 0;
  return userLevel >= requiredLevel;
}

/**
 * Utility function to check if a user has any of the specified roles
 */
export function hasAnyRole(userRole: UserRole, roles: UserRole[]): boolean {
  return hasRequiredRole(userRole, roles);
}
