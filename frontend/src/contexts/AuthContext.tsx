// MIT License -- see LICENSE-MIT
//
// Auth context provider for RenderTrust Creator.
// Manages JWT auth state, login/register/logout, and auto-refresh.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import {
  apiLogin,
  apiRegister,
  setTokens,
  clearTokens as clearApiTokens,
  getAccessToken,
  getRefreshToken,
} from "../lib/api";
import type {
  LoginRequest,
  RegisterRequest,
  TokenPair,
  ApiError,
} from "../lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface User {
  email: string;
}

export interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}

export interface AuthContextValue extends AuthState {
  login: (data: LoginRequest) => Promise<void>;
  register: (data: RegisterRequest) => Promise<void>;
  logout: () => Promise<void>;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

// ---------------------------------------------------------------------------
// Helpers -- Electron secure storage
// ---------------------------------------------------------------------------

async function persistTokens(tokens: TokenPair): Promise<void> {
  if (window.electronAPI?.setSecureToken) {
    await window.electronAPI.setSecureToken(
      "access_token",
      tokens.access_token,
    );
    await window.electronAPI.setSecureToken(
      "refresh_token",
      tokens.refresh_token,
    );
  } else {
    // Fallback for browser dev (non-Electron).  sessionStorage is acceptable
    // during development but tokens are NOT encrypted at rest.
    sessionStorage.setItem("access_token", tokens.access_token);
    sessionStorage.setItem("refresh_token", tokens.refresh_token);
  }
}

async function loadPersistedTokens(): Promise<{
  access: string | null;
  refresh: string | null;
}> {
  if (window.electronAPI?.getSecureToken) {
    const access = await window.electronAPI.getSecureToken("access_token");
    const refresh = await window.electronAPI.getSecureToken("refresh_token");
    return { access, refresh };
  }
  // Fallback for browser dev
  return {
    access: sessionStorage.getItem("access_token"),
    refresh: sessionStorage.getItem("refresh_token"),
  };
}

async function deletePersistedTokens(): Promise<void> {
  if (window.electronAPI?.deleteSecureToken) {
    await window.electronAPI.deleteSecureToken("access_token");
    await window.electronAPI.deleteSecureToken("refresh_token");
  } else {
    sessionStorage.removeItem("access_token");
    sessionStorage.removeItem("refresh_token");
  }
}

/** Decode the payload of a JWT (without verification -- server is the authority). */
function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const base64 = token.split(".")[1];
    if (!base64) return null;
    const json = atob(base64.replace(/-/g, "+").replace(/_/g, "/"));
    return JSON.parse(json) as Record<string, unknown>;
  } catch {
    return null;
  }
}

/** Extract user info from the access token payload. */
function userFromToken(token: string): User | null {
  const payload = decodeJwtPayload(token);
  if (!payload) return null;
  return {
    email: (payload.sub as string) || (payload.email as string) || "",
  };
}

/** Return seconds until the token expires (0 if already expired or unparseable). */
function secondsUntilExpiry(token: string): number {
  const payload = decodeJwtPayload(token);
  if (!payload || typeof payload.exp !== "number") return 0;
  return Math.max(0, payload.exp - Math.floor(Date.now() / 1000));
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

const REFRESH_MARGIN_SECONDS = 60; // refresh 60s before expiry

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // -----------------------------------------------------------------------
  // Schedule auto-refresh
  // -----------------------------------------------------------------------
  const scheduleRefresh = useCallback(() => {
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }

    const token = getAccessToken();
    if (!token) return;

    const ttl = secondsUntilExpiry(token);
    const delay = Math.max(0, (ttl - REFRESH_MARGIN_SECONDS) * 1000);

    if (delay <= 0) {
      // Token already near expiry -- refresh now
      void doRefresh();
      return;
    }

    refreshTimerRef.current = setTimeout(() => {
      void doRefresh();
    }, delay);
  }, []);

  const doRefresh = useCallback(async () => {
    const currentRefresh = getRefreshToken();
    if (!currentRefresh) return;

    try {
      const url = import.meta.env.VITE_API_BASE_URL
        ? `${import.meta.env.VITE_API_BASE_URL}/api/v1/auth/refresh`
        : "http://localhost:8000/api/v1/auth/refresh";

      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: currentRefresh }),
      });

      if (!response.ok) {
        // Refresh failed -- session expired
        clearApiTokens();
        await deletePersistedTokens();
        setUser(null);
        return;
      }

      const tokens = (await response.json()) as TokenPair;
      setTokens(tokens.access_token, tokens.refresh_token);
      await persistTokens(tokens);
      setUser(userFromToken(tokens.access_token));
      scheduleRefresh();
    } catch {
      // Network error -- will retry on next scheduled tick or user action
    }
  }, [scheduleRefresh]);

  // -----------------------------------------------------------------------
  // Restore session on mount
  // -----------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;

    async function restore() {
      try {
        const { access, refresh } = await loadPersistedTokens();
        if (cancelled) return;

        if (access && refresh) {
          setTokens(access, refresh);

          // Check if access token is still valid
          const ttl = secondsUntilExpiry(access);
          if (ttl > 0) {
            setUser(userFromToken(access));
            scheduleRefresh();
          } else {
            // Access token expired -- attempt refresh
            await doRefresh();
          }
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void restore();

    return () => {
      cancelled = true;
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
      }
    };
  }, [doRefresh, scheduleRefresh]);

  // -----------------------------------------------------------------------
  // Auth actions
  // -----------------------------------------------------------------------
  const login = useCallback(
    async (data: LoginRequest) => {
      const tokens = await apiLogin(data);
      setTokens(tokens.access_token, tokens.refresh_token);
      await persistTokens(tokens);
      setUser(userFromToken(tokens.access_token));
      scheduleRefresh();
    },
    [scheduleRefresh],
  );

  const register = useCallback(
    async (data: RegisterRequest) => {
      const tokens = await apiRegister(data);
      setTokens(tokens.access_token, tokens.refresh_token);
      await persistTokens(tokens);
      setUser(userFromToken(tokens.access_token));
      scheduleRefresh();
    },
    [scheduleRefresh],
  );

  const logout = useCallback(async () => {
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }
    clearApiTokens();
    await deletePersistedTokens();
    setUser(null);
  }, []);

  // -----------------------------------------------------------------------
  // Context value
  // -----------------------------------------------------------------------
  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isAuthenticated: user !== null,
      isLoading,
      login,
      register,
      logout,
    }),
    [user, isLoading, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (ctx === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}

export { AuthContext };
export type { ApiError };
