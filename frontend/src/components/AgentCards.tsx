import { AGENTS, TEAM, prettyTool } from "../agents";
import type { AgentName, BoardEvent, RunState } from "../types";

type Status = "idle" | "working" | "waiting" | "done";

function statusOf(agent: AgentName, events: BoardEvent[], run: RunState | null): Status {
  const mine = events.filter((e) => e.agent === agent);
  if (!mine.length) return "idle";
  if (run?.status === "running" && run.waiting_for_approval?.requested_by === agent) return "waiting";
  const last = mine[mine.length - 1];
  if (last.kind === "report" || last.kind === "delegation_result" || run?.status !== "running") return "done";
  return "working";
}

const STATUS_TEXT: Record<Status, string> = { idle: "Not called", working: "Working", waiting: "Waiting on you", done: "Done" };

export function AgentCards({ events, run }: { events: BoardEvent[]; run: RunState | null }) {
  const lastActive = [...events].reverse().find((e) => e.agent !== "human")?.agent;
  return (
    <section className="agents" aria-label="Agents">
      {TEAM.map((name) => {
        const meta = AGENTS[name];
        const mine = events.filter((e) => e.agent === name);
        const lastSaid = [...mine].reverse().find((e) => e.said && ["said", "report", "delegation"].includes(e.kind));
        const lastTool = [...mine].reverse().find((e) => e.kind === "tool_call")?.tools[0]?.tool;
        const status = statusOf(name, events, run);
        const live = run?.status === "running" && lastActive === name;
        return (
          <article
            key={name}
            className={`agent-card ${status} ${live ? "live" : ""}`}
            style={{ ["--agent" as string]: meta.color, ["--agent-tint" as string]: meta.tint }}
          >
            <div className="agent-head">
              <span className="avatar">{meta.monogram}</span>
              <h3>{meta.label}</h3>
            </div>
            <p className="role">{meta.role}</p>
            <span className={`agent-status ${status}`}>{live ? "Speaking…" : STATUS_TEXT[status]}</span>
            <p className="agent-said">{lastSaid?.said ?? (status === "idle" ? "Waiting to be called." : "…")}</p>
            {lastTool && <span className="chip tool">uses {prettyTool(lastTool)}</span>}
          </article>
        );
      })}
    </section>
  );
}
