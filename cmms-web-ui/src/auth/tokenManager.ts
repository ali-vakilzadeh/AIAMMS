/**
 * Token Manager
 * Handles in-memory storage and management of JWT tokens
 * Provides methods for getting, setting, refreshing, and clearing tokens
 */

export interface TokenType {
  accessToken: string;
  refreshToken: string;
  expiresAt?: number; // Timestamp when access token expires
}

class TokenManager {
  private accessToken: string | null = null;
  private refreshToken: string | null = null;
  private expiresAt: number | null = null;

  /**
   * Set authentication tokens
   */
  setTokens(tokens: TokenType): void {
    this.accessToken = tokens.accessToken;
    this.refreshToken = tokens.refreshToken;
    this.expiresAt = tokens.expiresAt || null;
  }

  /**
   * Get current access token
   */
  getAccessToken(): string | null {
    // Check if token is expired
    if (this.expiresAt && Date.now() >= this.expiresAt) {
      this.accessToken = null;
      return null;
    }
    return this.accessToken;
  }

  /**
   * Get current refresh token
   */
  getRefreshToken(): string | null {
    return this.refreshToken;
  }

  /**
   * Check if user is authenticated
   */
  isAuthenticated(): boolean {
    const token = this.getAccessToken();
    return token !== null && token.length > 0;
  }

  /**
   * Refresh the access token using refresh token
   * Note: This calls the API to refresh the token
   */
  async refreshTokenAsync(): Promise<TokenType | null> {
    const currentRefreshToken = this.getRefreshToken();
    
    if (!currentRefreshToken) {
      return null;
    }

    try {
      // Import apiClient dynamically to avoid circular dependency
      const { default: apiClient } = await import('../api/client');
      
      const response = await apiClient.post<{ data: TokenType }>('/auth/refresh', {
        refreshToken: currentRefreshToken,
      });

      const newTokens = response.data.data;
      
      // Update stored tokens
      this.setTokens(newTokens);
      
      return newTokens;
    } catch (error) {
      console.error('Token refresh failed:', error);
      this.clearTokens();
      return null;
    }
  }

  /**
   * Clear all tokens (logout)
   */
  clearTokens(): void {
    this.accessToken = null;
    this.refreshToken = null;
    this.expiresAt = null;
  }

  /**
   * Get token expiration time
   */
  getExpiresAt(): number | null {
    return this.expiresAt;
  }

  /**
   * Check if token is about to expire (within 5 minutes)
   */
  isTokenExpiringSoon(bufferMs: number = 5 * 60 * 1000): boolean {
    if (!this.expiresAt) return false;
    return Date.now() + bufferMs >= this.expiresAt;
  }
}

// Singleton instance
export const tokenManager = new TokenManager();
