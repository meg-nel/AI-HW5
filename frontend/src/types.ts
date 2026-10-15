// Shapes returned by the FastAPI routes in backend/main.py.

export type AgentName = "boss" | "inventory" | "accounting" | "facilities" | "customer_service" | "human";

export interface Ticket {
  id: number;
  type: string;
  requester: string;
  subject: string;
  status: string; // open | in_progress | waiting_on_human | waiting_on_vendor | resolved
  state: "open" | "resolved";
}

export interface TicketsResponse {
  shop_date: string;
  tickets: Ticket[];
}

export interface ApprovalRequest {
  approval_id: number;
  kind: "invoice_payment" | "rent_payment" | "purchase_order";
  amount: number;
  requested_by: string;
  reason: string | null;
  details: Record<string, unknown>;
}

export interface Approval {
  id: number;
  kind: ApprovalRequest["kind"];
  ref_id: number | null;
  amount: number;
  details: Record<string, unknown>;
  requested_by: string;
  reason: string | null;
  status: "pending" | "approved" | "rejected" | "paid";
  decided_by: string | null;
  decision_note: string | null;
}

export interface RunState {
  run_id: string | null;
  ticket_id: number | null;
  status: "idle" | "running" | "completed" | "error";
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  report: Record<string, unknown> | null;
  usage: { requests: number; tool_calls: number; input_tokens: number; output_tokens: number } | null;
  waiting_for_approval: ApprovalRequest | null;
  demo_mode?: boolean;
}

export interface ToolUse {
  tool: string;
  args?: Record<string, unknown>;
}

export interface BoardEvent {
  index: number;
  ts: string;
  run_id: string;
  agent: AgentName;
  chain: AgentName[];
  kind: string;
  said: string | null;
  tools: ToolUse[];
  to_agent?: AgentName;
  approval_id?: number;
  error?: boolean;
}

export interface EventsResponse {
  events: BoardEvent[];
  last_index: number;
  run: RunState;
}

export interface Cash {
  account: string;
  balance: number;
  as_of: string;
  shop_date: string;
  open_bills_total: number;
}

export interface AgentSummary {
  agent: AgentName;
  summary: string | null;
  decisions: { ticket_id: number; final_status: string; decision: string }[];
  actions: string[];
  tools: Record<string, number>;
  delegated_to: AgentName[];
  steps: number;
}

export interface RunSummary {
  run_id: string;
  status: string;
  usage: Record<string, number> | null;
  agents: AgentSummary[];
}
