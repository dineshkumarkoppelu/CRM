// Fetch wrapper for the FastAPI backend. Always relative /api paths (never a hard-coded host).
import type { ApiErrorBody } from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

function isErrorBody(body: unknown): body is ApiErrorBody {
  return (
    typeof body === "object" &&
    body !== null &&
    "error" in body &&
    typeof (body as ApiErrorBody).error?.message === "string"
  );
}

async function request<T>(method: string, path: string, body?: unknown, query?: Query): Promise<T> {
  let response: Response;
  try {
    response = await fetch(withQuery(`/api${path}`, query), {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "Cannot reach the API. Is it running on port 8000?");
  }

  const text = await response.text();
  let parsed: unknown = undefined;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = undefined;
    }
  }

  if (!response.ok) {
    if (isErrorBody(parsed)) {
      const { code, message, details } = parsed.error;
      throw new ApiError(response.status, code, message, details);
    }
    throw new ApiError(response.status, `HTTP_${response.status}`, response.statusText || "Request failed");
  }
  return parsed as T;
}

export const api = {
  get: <T>(path: string, query?: Query) => request<T>("GET", path, undefined, query),
  post: <T>(path: string, body?: unknown, query?: Query) => request<T>("POST", path, body ?? {}, query),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
};

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    // 422s carry pydantic's list of field errors; show them instead of the generic message.
    const errors = error.details.errors;
    if (error.code === "VALIDATION_ERROR" && Array.isArray(errors) && errors.length > 0) {
      return errors
        .map((e: { loc?: unknown[]; msg?: string }) => {
          const field = (e.loc ?? []).filter((p) => p !== "body").join(".");
          const msg = (e.msg ?? "invalid value").replace(/^Value error, /, "");
          return field ? `${field}: ${msg}` : msg;
        })
        .join("; ");
    }
    return error.message;
  }
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}
