// Fetch wrapper for the ERP API (/api/v1/erp). Sends the bearer token from sessionStorage and
// returns to the login screen on any 401 (research R-12). All storage access is guarded: it can
// throw in private windows or when site data is blocked.

const BASE = "/api/v1/erp";
const TOKEN_KEY = "erp_token";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string;

  constructor(status: number, code: string, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

let unauthenticatedHandler: (() => void) | null = null;

/** The router registers a function that sends the manager to /login. */
export function setUnauthenticatedHandler(handler: (() => void) | null): void {
  unauthenticatedHandler = handler;
}

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function storeToken(token: string | null): void {
  try {
    if (token === null) sessionStorage.removeItem(TOKEN_KEY);
    else sessionStorage.setItem(TOKEN_KEY, token);
  } catch {
    // Storage unavailable: the manager has to sign in again on reload.
  }
}

export function isSignedIn(): boolean {
  return getToken() !== null;
}

type JsonBody = Record<string, unknown> | unknown[];
export type ApiInit = Omit<RequestInit, "body"> & { body?: BodyInit | JsonBody | null };

function isJsonBody(body: ApiInit["body"]): body is JsonBody {
  return (
    body !== null &&
    typeof body === "object" &&
    !(body instanceof FormData) &&
    !(body instanceof Blob) &&
    !(body instanceof URLSearchParams) &&
    !(body instanceof ArrayBuffer)
  );
}

export async function apiFetch<T>(path: string, init: ApiInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token !== null) headers.set("Authorization", `Bearer ${token}`);

  let body: BodyInit | null | undefined;
  if (isJsonBody(init.body)) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.body);
  } else {
    body = init.body; // FormData and the like: the browser sets the multipart Content-Type itself.
  }

  const response = await fetch(`${BASE}${path}`, { ...init, headers, body });

  if (!response.ok) {
    let code = "HTTP_ERROR";
    let detail = `Request failed (${response.status})`;
    try {
      const payload = (await response.json()) as { code?: string; detail?: string };
      code = payload.code ?? code;
      detail = payload.detail ?? detail;
    } catch {
      // Not a JSON error body: keep the generic message.
    }
    if (response.status === 401) {
      storeToken(null);
      unauthenticatedHandler?.();
    }
    throw new ApiError(response.status, code, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function login(username: string, password: string): Promise<void> {
  const result = await apiFetch<{ access_token: string }>("/auth/login", {
    method: "POST",
    body: { username, password },
  });
  storeToken(result.access_token);
}

export function logout(): void {
  storeToken(null);
}
