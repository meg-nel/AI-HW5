import type { AgentName } from "./types";

// Each agent has its own warm color, monogram, and one-line role, so its lines read differently
// everywhere on the board (agent cards, the conversation, the summary).
export interface AgentMeta {
  name: AgentName;
  label: string;
  monogram: string;
  role: string;
  color: string; // solid accent
  tint: string; // soft background for its bubbles
}

export const AGENTS: Record<AgentName, AgentMeta> = {
  boss: { name: "boss", label: "Boss", monogram: "B", role: "Reads tickets, routes work, makes the call",
    color: "#b4532e", tint: "#fbe4d8" },
  inventory: { name: "inventory", label: "Inventory", monogram: "In", role: "Stock by size, shortfalls, vendors",
    color: "#7a7d3a", tint: "#eef0dc" },
  accounting: { name: "accounting", label: "Accounting", monogram: "Ac", role: "Cash, margins, prepares payments",
    color: "#c9851c", tint: "#fcefd2" },
  facilities: { name: "facilities", label: "Facilities", monogram: "Fa", role: "Lease, rent, landlord",
    color: "#a55a6a", tint: "#f7e1e4" },
  customer_service: { name: "customer_service", label: "Customer Service", monogram: "CS", role: "Drafts replies (never sent)",
    color: "#d96c4f", tint: "#fde3da" },
  human: { name: "human", label: "You", monogram: "You", role: "Approves payments and orders",
    color: "#6b4a6e", tint: "#efe4f0" },
};

export const TEAM: AgentName[] = ["boss", "inventory", "accounting", "facilities", "customer_service"];

export const prettyTool = (tool: string) => tool.replace(/_/g, " ");

export const money = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });
