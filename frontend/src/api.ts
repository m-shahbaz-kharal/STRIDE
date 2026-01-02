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
  data: GraphData;
  created_at: string;
  updated_at: string;
}

export interface GraphData {
  nodes: any[];
  edges: any[];
  ui?: {
    leftPanelCollapsed?: boolean;
    rightPanelCollapsed?: boolean;
    leftPanelWidth?: number;
    rightPanelWidth?: number;
  };
}

const SESSION_KEY = "liguard_session";

export const readSession = (): AuthSession | null => {
  const raw = localStorage.getItem(SESSION_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthSession;
  } catch {
    return null;
  }
};

export const writeSession = (session: AuthSession | null) => {
  if (!session) {
    localStorage.removeItem(SESSION_KEY);
  } else {
    localStorage.setItem(SESSION_KEY, JSON.stringify(session));
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

export const createGraph = (session: AuthSession, payload: { name: string; data: GraphData }) =>
  apiRequest<GraphRecord>("/api/graphs", {
    method: "POST",
    body: JSON.stringify(payload),
  }, session);

export const updateGraph = (session: AuthSession, graphId: string, payload: { name?: string; data?: GraphData }) =>
  apiRequest<GraphRecord>(`/api/graphs/${graphId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  }, session);

export const deleteGraph = (session: AuthSession, graphId: string) =>
  apiRequest<{ deleted: boolean }>(`/api/graphs/${graphId}`, {
    method: "DELETE",
  }, session);
