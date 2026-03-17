const API_KEY = localStorage.getItem("devmaker_api_key") || "";

async function apiFetch(path: string, options: RequestInit = {}) {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "x-api-key": API_KEY,
    ...(options.headers as Record<string, string> || {}),
  };
  const res = await fetch(path, { ...options, headers });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

export function setApiKey(key: string) {
  localStorage.setItem("devmaker_api_key", key);
  window.location.reload();
}

export function getApiKey() {
  return localStorage.getItem("devmaker_api_key") || "";
}

export const api = {
  accounts: {
    list: () => apiFetch("/api/accounts"),
    create: (name: string) => apiFetch("/api/accounts", { method: "POST", body: JSON.stringify({ name }) }),
    delete: (id: string) => apiFetch(`/api/accounts/${id}`, { method: "DELETE" }),
    start: (id: string, count = 1) => apiFetch(`/api/accounts/${id}/start`, { method: "POST", body: JSON.stringify({ count }) }),
    stop: (id: string) => apiFetch(`/api/accounts/${id}/stop`, { method: "POST" }),
    status: (id: string) => apiFetch(`/api/accounts/${id}/status`),
  },
  config: {
    get: (accountId: string) => apiFetch(`/api/config/${accountId}`),
    update: (accountId: string, data: Record<string, any>) => apiFetch(`/api/config/${accountId}`, { method: "PUT", body: JSON.stringify(data) }),
  },
  logs: {
    get: (accountId: string, limit = 100) => apiFetch(`/api/logs/${accountId}?limit=${limit}`),
  },
};
