import type { BoardEvent, RunState, Ticket } from "./types";

// The board's colors follow a day: dawn before anything runs, sunrise as the team starts,
// midday while it works, golden hour while it waits for you, sunset when the run is done,
// and dusk once every ticket is resolved.
export type Phase = "dawn" | "sunrise" | "midday" | "golden" | "sunset" | "dusk";

export const PHASE_LABEL: Record<Phase, string> = {
  dawn: "Dawn · pick a ticket to start the day",
  sunrise: "Sunrise · the team is reading the ticket",
  midday: "Midday · the team is working",
  golden: "Golden hour · waiting for your approval",
  sunset: "Sunset · the run is done",
  dusk: "Dusk · every ticket is resolved",
};

export interface Milestone {
  key: string;
  label: string;
  done: boolean;
}

// Progress through one run, read from its events.
export function milestones(events: BoardEvent[], run: RunState | null): Milestone[] {
  const has = (pred: (e: BoardEvent) => boolean) => events.some(pred);
  const toolUsed = (name: string) => has((e) => e.kind === "tool_call" && e.tools.some((t) => t.tool === name));
  const approvalAsked = has((e) => e.kind === "approval_requested");
  return [
    { key: "read", label: "Ticket read", done: toolUsed("get_ticket") },
    { key: "brief", label: "Team briefed", done: has((e) => e.kind === "delegation") },
    {
      key: "approval",
      label: approvalAsked ? "Approval decided" : "Money plan",
      done: approvalAsked
        ? has((e) => ["approval_decided", "human_approved", "human_rejected"].includes(e.kind))
        : has((e) => e.kind === "delegation" && e.to_agent === "accounting") || has((e) => e.kind === "delegation_result" && e.agent === "accounting"),
    },
    { key: "draft", label: "Reply drafted", done: toolUsed("draft_customer_message") },
    { key: "update", label: "Ticket updated", done: toolUsed("update_ticket") },
    { key: "done", label: "Run finished", done: run?.status === "completed" || run?.status === "error" },
  ];
}

export function progress(ms: Milestone[]): number {
  return ms.filter((m) => m.done).length / ms.length;
}

export function phaseFor(run: RunState | null, ms: Milestone[], tickets: Ticket[]): Phase {
  const allResolved = tickets.length > 0 && tickets.every((t) => t.state === "resolved");
  if (run?.status === "running") {
    if (run.waiting_for_approval) return "golden";
    return progress(ms) < 0.34 ? "sunrise" : "midday";
  }
  if (allResolved) return "dusk";
  if (run && (run.status === "completed" || run.status === "error")) return "sunset";
  return "dawn";
}

// Where the sun sits on its arc (0 = left horizon, 1 = right horizon).
export function sunPosition(phase: Phase, p: number): number {
  switch (phase) {
    case "dawn": return 0.04;
    case "sunrise": return 0.1 + p * 0.5;
    case "midday": return 0.1 + p * 0.7;
    case "golden": return Math.max(0.62, 0.1 + p * 0.7);
    case "sunset": return 0.9;
    case "dusk": return 0.98;
  }
}
