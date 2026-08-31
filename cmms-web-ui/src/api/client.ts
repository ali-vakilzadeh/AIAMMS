import axios from 'axios';
import type { AxiosInstance, AxiosError, AxiosResponse, InternalAxiosRequestConfig } from '../axios-types';
import { tokenManager } from '../auth/tokenManager';

// Base API URL from environment
const BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

// Create axios instance
const apiClient: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30000, // 30 seconds
});

// Request interceptor: Inject JWT token
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const accessToken = tokenManager.getAccessToken();
    
    if (accessToken && config.headers) {
      config.headers.Authorization = `Bearer ${accessToken}`;
    }
    
    return config;
  },
  (error: AxiosError) => Promise.reject(error)
);

// Response interceptor: Handle 401 errors and token refresh
apiClient.interceptors.response.use(
  (response: AxiosResponse) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean };
    
    // If error is 401 and we haven't retried yet
    if (error.response?.status === 401 && !originalRequest._retry) {
      if (originalRequest._retry) {
        // Already retried, prevent infinite loop
        return Promise.reject(error);
      }
      
      originalRequest._retry = true;
      
      try {
        // Attempt to refresh the token
        const newTokens = await tokenManager.refreshTokenAsync();
        
        if (newTokens && originalRequest.headers) {
          // Retry original request with new token
          originalRequest.headers.Authorization = `Bearer ${newTokens.accessToken}`;
          return apiClient(originalRequest);
        }
      } catch (refreshError) {
        // Refresh failed, clear tokens and redirect to login
        tokenManager.clearTokens();
        
        // Dispatch custom event for auth failure
        window.dispatchEvent(new CustomEvent('auth:sessionExpired'));
        
        return Promise.reject(refreshError);
      }
    }
    
    return Promise.reject(error);
  }
);

export default apiClient;
