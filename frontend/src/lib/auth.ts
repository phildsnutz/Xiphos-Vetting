/**
 * Helios Auth Module
 *
 * Manages JWT bearer tokens, user identity, and session state.
 * Tokens are stored in sessionStorage (cleared on tab close).
 */

const BASE = import.meta.env.VITE_API_URL ?? "";

export interface AuthUser {
  sub: string;
  email: string;
  name: string;
  role: "admin" | "analyst" | "auditor" | "reviewer";
}

export interface LoginResponse {
  token: string;
  user: AuthUser;
}

export interface SetupResponse {
  token: string;
  user: AuthUser;
}

const TOKEN_KEY = "helios_token";
const USER_KEY = "helios_user";

// ---- Token storage ----

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function getUser(): AuthUser | null {
  const raw = sessionStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

export function setSession(token: string, user: AuthUser): void {
  sessionStorage.setItem(TOKEN_KEY, token);
  sessionStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession(): void {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(USER_KEY);
}

// ---- Auth API calls ----

async function authFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
    throw new Error(body.error || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  const data = await authFetch<LoginResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  setSession(data.token, data.user);
  return data;
}

export async function setup(email: string, password: string, name: string): Promise<SetupResponse> {
  const data = await authFetch<SetupResponse>("/api/auth/setup", {
    method: "POST",
    body: JSON.stringify({ email, password, name }),
  });
  setSession(data.token, data.user);
  return data;
}

export async function fetchMe(): Promise<AuthUser> {
  const token = getToken();
  if (!token) throw new Error("No token");
  return authFetch<AuthUser>("/api/auth/me", {
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
  });
}

/**
 * Check if auth is enabled on the server.
 * Returns true if the health endpoint requires a token (returns 401 without one).
 * Returns false if auth is disabled (dev mode).
 */
export async function checkAuthEnabled(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/api/health`);
    if (res.status === 401) return true;
    const data = await res.json() as {
      auth_enabled?: boolean;
      login_required?: boolean;
      dev_mode?: boolean;
    };
    if (typeof data.login_required === "boolean") {
      return data.login_required;
    }
    if (data.auth_enabled === true) return true;
    if (data.auth_enabled === false) {
      return data.dev_mode !== true;
    }
    return true;
  } catch {
    // Default to auth-required when the probe fails so the UI does not
    // silently downgrade into an unauthenticated state on transport errors.
    return true;
  }
}

// ---- Role helpers ----

const ROLE_LEVELS: Record<string, number> = {
  admin: 100,
  analyst: 50,
  auditor: 30,
  reviewer: 20,
};

export function hasPermission(user: AuthUser | null, minRole: string): boolean {
  if (!user) return false;
  const userLevel = ROLE_LEVELS[user.role] ?? 0;
  const requiredLevel = ROLE_LEVELS[minRole] ?? 100;
  return userLevel >= requiredLevel;
}

export function roleLabel(role: string): string {
  const labels: Record<string, string> = {
    admin: "Administrator",
    analyst: "Analyst",
    auditor: "Auditor",
    reviewer: "Reviewer",
  };
  return labels[role] ?? role;
}
