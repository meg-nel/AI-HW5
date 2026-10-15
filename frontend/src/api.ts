import { API_BASE } from "./config";
import type { Approval, Cash, EventsResponse, RunState, RunSummary, TicketsResponse } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, `Can't reach the backend at ${API_BASE}`);
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof body?.detail === "string" ? body.detail : JSON.stringify(body?.detail ?? body);
    throw new ApiError(res.status, detail);
  }
  return body as T;
}

export const api = {
  tickets: () => call<TicketsResponse>("/tickets"),
  runTicket: (id: number) => call<{ run_id: string; status: string }>(`/tickets/${id}/run`, { method: "POST" }),
  currentRun: () => call<RunState>("/runs/current"),
  summary: (runId: string) => call<RunSummary>(`/runs/${encodeURIComponent(runId)}/summary`),
  events: (runId: string, after?: number) =>
    call<EventsResponse>(
      `/events?limit=500&run_id=${encodeURIComponent(runId)}${after !== undefined ? `&after=${after}` : ""}`,
    ),
  approvals: () => call<Approval[]>("/approvals?status=pending"),
  approve: (id: number, approvedBy: string, note = "") =>
    call<{ checking_balance?: number }>(`/approvals/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ approved_by: approvedBy, note }),
    }),
  reject: (id: number, approvedBy: string, note = "") =>
    call<unknown>(`/approvals/${id}/reject`, { method: "POST", body: JSON.stringify({ approved_by: approvedBy, note }) }),
  cash: () => call<Cash>("/cash"),
  reset: () => call<unknown>("/reset", { method: "POST" }),
};
