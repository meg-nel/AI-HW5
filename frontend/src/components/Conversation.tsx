import { useEffect, useRef } from "react";
import { AGENTS, prettyTool } from "../agents";
import type { BoardEvent } from "../types";

// Which events appear in the conversation. Plain tool calls are shown as chips on the agent's
// "said" line instead; successful tool results stay in the audit trail.
function visible(e: BoardEvent): boolean {
  if (e.kind === "tool_call") return false;
  if (e.kind === "tool_result") return !!e.error;
  if (e.kind === "task") return e.agent === "boss";
  // A teammate's final report is shown once, as "X reports to Boss".
  if (e.kind === "report") return e.agent === "boss";
  return true;
}

function Line({ e }: { e: BoardEvent }) {
  const meta = AGENTS[e.agent] ?? AGENTS.human;
  const to = e.to_agent ? AGENTS[e.to_agent] : null;
  const style = { ["--agent" as string]: meta.color, ["--agent-tint" as string]: meta.tint };
  const time = new Date(e.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

  if (e.kind === "run_start" || e.kind === "run_end") {
    return <li className="divider"><span>{e.kind === "run_start" ? "Run started" : `Run ${e.said}`} · {time}</span></li>;
  }

  let title: string = meta.label;
  let cls = "bubble";
  if (e.kind === "delegation" && to) title = `${meta.label} → ${to.label}`;
  if (e.kind === "delegation_result" && to) title = `${meta.label} reports to ${to.label}`;
  if (e.kind === "report") { title = `${meta.label} · final report`; cls += " report"; }
  if (e.kind === "task") title = "Ticket handed to the Boss";
  if (["approval_requested", "waiting_for_human"].includes(e.kind)) cls += " ask";
  if (["approval_decided", "human_approved", "human_rejected", "payment_made"].includes(e.kind)) cls += " decision";
  if (e.error || e.kind === "payment_refused") cls += " problem";

  return (
    <li className={cls} style={style}>
      <span className="avatar small">{meta.monogram}</span>
      <div className="bubble-body">
        <div className="bubble-head">
          <strong>{title}</strong>
          <time>{time}</time>
        </div>
        {e.said && <p>{e.kind === "task" ? e.said.split(". ")[0] + "." : e.said}</p>}
        {e.tools.length > 0 && (
          <div className="chips">
            {e.tools.map((t, i) => (
              <span key={i} className="chip tool" title={t.args ? JSON.stringify(t.args) : undefined}>
                {prettyTool(t.tool)}
              </span>
            ))}
          </div>
        )}
      </div>
    </li>
  );
}

export function Conversation({ events, running }: { events: BoardEvent[]; running: boolean }) {
  const shown = events.filter(visible);
  const end = useRef<HTMLLIElement>(null);
  useEffect(() => {
    if (running) end.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [shown.length, running]);
  return (
    <section className="conversation" aria-label="What the agents are saying">
      <div className="panel-head">
        <h2>On the desk</h2>
        <span className="count">{shown.length} updates</span>
      </div>
      {shown.length === 0 ? (
        <p className="empty">Start the team on a ticket to watch the agents talk it through.</p>
      ) : (
        <ol>
          {shown.map((e) => <Line key={e.index} e={e} />)}
          <li ref={end} className="end" aria-hidden="true" />
        </ol>
      )}
    </section>
  );
}
