import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import { tokenManager, TokenType } from '../auth/tokenManager';
import apiClient from '../api/client';
import { UserRole } from '@/lib/constants';

// User profile interface
export interface UserProfile {
  id: string;
  email: string;
  firstName: string;
  lastName: string;
  role: UserRole;
  organizationId: string;
  avatarUrl?: string;
}

// Auth context state
interface AuthState {
  user: UserProfile | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  error: string | null;
}

// Auth context actions
interface AuthActions {
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string, firstName: string, lastName: string) => Promise<void>;
  logout: () => void;
  forgotPassword: (email: string) => Promise<void>;
  resetPassword: (token: string, newPassword: string) => Promise<void>;
  updateUser: (updates: Partial<UserProfile>) => void;
  clearError: () => void;
}

type AuthContextType = AuthState & AuthActions;

const AuthContext = createContext<AuthContextType | undefined>(undefined);

// API response types
interface LoginResponse {
  data: {
    user: UserProfile;
    tokens: TokenType;
  };
}

interface SignupResponse {
  data: {
    user: UserProfile;
    tokens: TokenType;
  };
}

interface ForgotPasswordResponse {
  data: {
    message: string;
  };
}

interface ResetPasswordResponse {
  data: {
    message: string;
  };
}

interface AuthProviderProps {
  children: ReactNode;
}

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Initialize auth state on mount
  useEffect(() => {
    const initAuth = async () => {
      try {
        if (tokenManager.isAuthenticated()) {
          // Fetch current user profile if we have a valid token
          const response = await apiClient.get<{ data: UserProfile }>('/auth/me');
          setUser(response.data.data);
        }
      } catch (err) {
        console.error('Failed to initialize auth:', err);
        tokenManager.clearTokens();
        setUser(null);
      } finally {
        setIsLoading(false);
      }
    };

    initAuth();

    // Listen for session expired events
    const handleSessionExpired = () => {
      setUser(null);
      setError('Your session has expired. Please log in again.');
    };

    window.addEventListener('auth:sessionExpired', handleSessionExpired);

    return () => {
      window.removeEventListener('auth:sessionExpired', handleSessionExpired);
    };
  }, []);

  // Login function
  const login = useCallback(async (email: string, password: string): Promise<void> => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await apiClient.post<LoginResponse>('/auth/login', {
        email,
        password,
      });

      const { user: userData, tokens } = response.data.data;
      
      // Store tokens
      tokenManager.setTokens(tokens);
      
      // Set user
      setUser(userData);
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Login failed';
      setError(errorMessage);
      throw new Error(errorMessage);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Signup function
  const signup = useCallback(
    async (email: string, password: string, firstName: string, lastName: string): Promise<void> => {
      setIsLoading(true);
      setError(null);

      try {
        const response = await apiClient.post<SignupResponse>('/auth/signup', {
          email,
          password,
          firstName,
          lastName,
        });

        const { user: userData, tokens } = response.data.data;
        
        // Store tokens
        tokenManager.setTokens(tokens);
        
        // Set user
        setUser(userData);
      } catch (err: unknown) {
        const errorMessage = err instanceof Error ? err.message : 'Signup failed';
        setError(errorMessage);
        throw new Error(errorMessage);
      } finally {
        setIsLoading(false);
      }
    },
    []
  );

  // Logout function
  const logout = useCallback(() => {
    tokenManager.clearTokens();
    setUser(null);
    setError(null);
    
    // Optionally call backend to invalidate refresh token
    apiClient.post('/auth/logout').catch(() => {
      // Ignore errors on logout
    });
  }, []);

  // Forgot password function
  const forgotPassword = useCallback(async (email: string): Promise<void> => {
    setIsLoading(true);
    setError(null);

    try {
      await apiClient.post<ForgotPasswordResponse>('/auth/forgot-password', { email });
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to send reset email';
      setError(errorMessage);
      throw new Error(errorMessage);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Reset password function
  const resetPassword = useCallback(
    async (token: string, newPassword: string): Promise<void> => {
      setIsLoading(true);
      setError(null);

      try {
        await apiClient.post<ResetPasswordResponse>('/auth/reset-password', {
          token,
          newPassword,
        });
      } catch (err: unknown) {
        const errorMessage = err instanceof Error ? err.message : 'Failed to reset password';
        setError(errorMessage);
        throw new Error(errorMessage);
      } finally {
        setIsLoading(false);
      }
    },
    []
  );

  // Update user function
  const updateUser = useCallback((updates: Partial<UserProfile>) => {
    setUser((prev) => (prev ? { ...prev, ...updates } : null));
  }, []);

  // Clear error function
  const clearError = useCallback(() => {
    setError(null);
  }, []);

  const value: AuthContextType = {
    user,
    isLoading,
    isAuthenticated: !!user && tokenManager.isAuthenticated(),
    error,
    login,
    signup,
    logout,
    forgotPassword,
    resetPassword,
    updateUser,
    clearError,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

// Custom hook to use auth context
export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  
  return context;
};
