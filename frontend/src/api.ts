import { Node, Edge } from "reactflow";
import { BlueprintNodeData, DashboardLayout } from "./types";

export interface User {
  id: string;
  email: string;
  display_name?: string | null;
}

export interface AuthSession {
  token: string;
  user: User;
}

interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface GraphRecord {
  id: string;
  name: string;
  description?: string | null;
  data: GraphData;
  created_at: string;
  updated_at: string;
}

export interface GraphData {
  nodes: Node<BlueprintNodeData>[];
  edges: Edge[];
  ui?: {
    leftPanelCollapsed?: boolean;
    rightPanelCollapsed?: boolean;
    leftPanelWidth?: number;
    rightPanelWidth?: number;
  };
  dashboard?: DashboardLayout;
}

const SESSION_KEY = "stride_session";

export const readSession = (): AuthSession | null => {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as AuthSession;
  } catch {
    // localStorage may be disabled (private browsing) or contain a
    // malformed payload. In either case there's no usable session.
    return null;
  }
};

export const writeSession = (session: AuthSession | null) => {
  try {
    if (!session) {
      localStorage.removeItem(SESSION_KEY);
    } else {
      localStorage.setItem(SESSION_KEY, JSON.stringify(session));
    }
  } catch (e) {
    // QuotaExceededError in private browsing / out-of-space. Don't
    // crash the auth flow; the user can still operate within the tab.
    console.warn("writeSession: localStorage write failed", e);
  }
};

const apiRequest = async <T>(path: string, options: RequestInit = {}, session?: AuthSession | null): Promise<T> => {
  const headers = new Headers(options.headers || {});
  headers.set("Content-Type", "application/json");
  if (session?.token) {
    headers.set("Authorization", `Bearer ${session.token}`);
  }
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
};

/**
 * Bare ``fetch`` wrapper that auto-attaches the bearer token from the
 * persisted session. Use this for endpoints (cancel, cache-clear,
 * stream-frame, etc.) that aren't already routed through the
 * ``apiRequest`` helper above. Returns the raw ``Response`` so callers
 * can inspect status codes.
 */
export const authFetch = (path: string, init: RequestInit = {}): Promise<Response> => {
  const headers = new Headers(init.headers || {});
  const session = readSession();
  if (session?.token) {
    headers.set("Authorization", `Bearer ${session.token}`);
  }
  return fetch(path, { ...init, headers });
};

const toSession = (response: TokenResponse): AuthSession => ({
  token: response.access_token,
  user: response.user,
});

export const registerUser = async (payload: { email: string; password: string; display_name?: string | null }) => {
  const response = await apiRequest<TokenResponse>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return toSession(response);
};

export const loginUser = async (payload: { email: string; password: string }) => {
  const response = await apiRequest<TokenResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return toSession(response);
};

export const fetchMe = (session: AuthSession) =>
  apiRequest<User>("/api/auth/me", {}, session);

export const listGraphs = (session: AuthSession) =>
  apiRequest<GraphRecord[]>("/api/graphs", {}, session);

export const createGraph = (session: AuthSession, payload: { name: string; description?: string | null; data: GraphData }) =>
  apiRequest<GraphRecord>("/api/graphs", {
    method: "POST",
    body: JSON.stringify(payload),
  }, session);

export const updateGraph = (session: AuthSession, graphId: string, payload: { name?: string; description?: string | null; data?: GraphData }) =>
  apiRequest<GraphRecord>(`/api/graphs/${graphId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  }, session);

export const deleteGraph = (session: AuthSession, graphId: string) =>
  apiRequest<{ deleted: boolean }>(`/api/graphs/${graphId}`, {
    method: "DELETE",
  }, session);
