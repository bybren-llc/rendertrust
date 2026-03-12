// MIT License -- see LICENSE-MIT
//
// API client for RenderTrust backend.
// Handles base URL configuration, JWT auth headers, and auto-refresh on 401.

/** Determine API base URL from environment or Electron config */
function getBaseUrl(): string {
  // Vite injects env vars prefixed with VITE_
  if (import.meta.env.VITE_API_BASE_URL) {
    return import.meta.env.VITE_API_BASE_URL as string;
  }
  // Default: local FastAPI dev server
  return "http://localhost:8000";
}

const API_BASE_URL = getBaseUrl();

/** Shape of the JWT token pair returned by the backend */
export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

/** In-memory token store (populated from secure storage on app start) */
let accessToken: string | null = null;
let refreshToken: string | null = null;

/** Flag to avoid concurrent refresh attempts */
let isRefreshing = false;
let refreshPromise: Promise<boolean> | null = null;

// ---------------------------------------------------------------------------
// Token management
// ---------------------------------------------------------------------------

export function setTokens(access: string, refresh: string): void {
  accessToken = access;
  refreshToken = refresh;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function getRefreshToken(): string | null {
  return refreshToken;
}

export function clearTokens(): void {
  accessToken = null;
  refreshToken = null;
}

// ---------------------------------------------------------------------------
// Core fetch wrapper
// ---------------------------------------------------------------------------

export interface ApiError {
  status: number;
  detail: string;
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const url = `${API_BASE_URL}${path}`;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> | undefined),
  };

  if (accessToken) {
    headers["Authorization"] = `Bearer ${accessToken}`;
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });

  // If 401 and we have a refresh token, attempt refresh then retry once
  if (response.status === 401 && refreshToken) {
    const refreshed = await attemptTokenRefresh();
    if (refreshed) {
      // Retry the original request with new access token
      headers["Authorization"] = `Bearer ${accessToken}`;
      const retryResponse = await fetch(url, {
        ...options,
        headers,
      });

      if (!retryResponse.ok) {
        const errorBody = await retryResponse.json().catch(() => ({
          detail: retryResponse.statusText,
        }));
        const err: ApiError = {
          status: retryResponse.status,
          detail: errorBody.detail || retryResponse.statusText,
        };
        throw err;
      }

      return retryResponse.json() as Promise<T>;
    }

    // Refresh failed -- clear tokens, let caller handle redirect
    clearTokens();
    const err: ApiError = { status: 401, detail: "Session expired" };
    throw err;
  }

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({
      detail: response.statusText,
    }));
    const err: ApiError = {
      status: response.status,
      detail: errorBody.detail || response.statusText,
    };
    throw err;
  }

  // Some endpoints may return 204 No Content
  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Token refresh
// ---------------------------------------------------------------------------

async function attemptTokenRefresh(): Promise<boolean> {
  if (isRefreshing && refreshPromise) {
    return refreshPromise;
  }

  isRefreshing = true;
  refreshPromise = doRefresh();
  const result = await refreshPromise;
  isRefreshing = false;
  refreshPromise = null;
  return result;
}

async function doRefresh(): Promise<boolean> {
  try {
    const url = `${API_BASE_URL}/api/v1/auth/refresh`;
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (!response.ok) {
      return false;
    }

    const data = (await response.json()) as TokenPair;
    accessToken = data.access_token;
    refreshToken = data.refresh_token;

    // Persist refreshed tokens to Electron secure storage
    if (window.electronAPI?.setSecureToken) {
      await window.electronAPI.setSecureToken(
        "access_token",
        data.access_token,
      );
      await window.electronAPI.setSecureToken(
        "refresh_token",
        data.refresh_token,
      );
    }

    return true;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Auth API endpoints
// ---------------------------------------------------------------------------

export interface LoginRequest {
  email: string;
  password: string;
}

export interface RegisterRequest {
  email: string;
  password: string;
}

export async function apiLogin(data: LoginRequest): Promise<TokenPair> {
  return request<TokenPair>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function apiRegister(data: RegisterRequest): Promise<TokenPair> {
  return request<TokenPair>("/api/v1/auth/register", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function apiRefreshToken(): Promise<TokenPair> {
  return request<TokenPair>("/api/v1/auth/refresh", {
    method: "POST",
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
}

// ---------------------------------------------------------------------------
// Generic typed API methods
// ---------------------------------------------------------------------------

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "PUT",
      body: body ? JSON.stringify(body) : undefined,
    }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

export default api;
