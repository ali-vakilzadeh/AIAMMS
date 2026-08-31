import React, { ReactNode } from 'react';
import { useAuth } from './AuthProvider';

interface RequireAuthProps {
  children: ReactNode;
  fallback?: ReactNode;
}

/**
 * RequireAuth Component
 * Protects routes that require authentication.
 * Redirects to login page if user is not authenticated.
 */
export const RequireAuth: React.FC<RequireAuthProps> = ({ 
  children, 
  fallback = null 
}) => {
  const { isAuthenticated, isLoading } = useAuth();

  // Show loading state while checking auth
  if (isLoading) {
    return fallback || (
      <div className="flex h-screen w-full items-center justify-center">
        <div className="animate-spin rounded-full border-4 border-primary border-t-transparent h-12 w-12" />
      </div>
    );
  }

  // Redirect to login if not authenticated
  if (!isAuthenticated) {
    // In a real app, you'd use react-router to redirect
    // For now, we return null and let the routing system handle it
    window.location.href = '/login';
    return fallback || null;
  }

  return <>{children}</>;
};
