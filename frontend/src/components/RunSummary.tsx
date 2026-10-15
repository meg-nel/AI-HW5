import { AGENTS, prettyTool } from "../agents";
import type { RunSummary as Summary } from "../types";

export function RunSummary({ summary }: { summary: Summary }) {
  return (
    <section className="summary" aria-label="What each agent did">
      <div className="panel-head">
        <h2>What each agent did</h2>
        {summary.usage && (
          <span className="count">
            {summary.usage.requests} model calls · {summary.usage.tool_calls} tool calls ·{" "}
            {Math.round(((summary.usage.input_tokens ?? 0) + (summary.usage.output_tokens ?? 0)) / 1000)}k tokens
          </span>
        )}
      </div>
      <div className="summary-grid">
        {summary.agents.map((a) => {
          const meta = AGENTS[a.agent];
          return (
            <article key={a.agent} className="summary-card"
              style={{ ["--agent" as string]: meta.color, ["--agent-tint" as string]: meta.tint }}>
              <div className="agent-head">
                <span className="avatar">{meta.monogram}</span>
                <h3>{meta.label}</h3>
              </div>
              {a.decisions.map((d) => (
                <p key={d.ticket_id} className="decision"><strong>#{d.ticket_id} → {d.final_status.replace(/_/g, " ")}:</strong> {d.decision}</p>
              ))}
              {a.summary && <p>{a.summary}</p>}
              {a.actions.length > 0 && (
                <ul>{a.actions.slice(0, 4).map((x, i) => <li key={i}>{x}</li>)}</ul>
              )}
              <div className="chips">
                {a.delegated_to.map((t, i) => <span key={`d${i}`} className="chip handoff">→ {AGENTS[t]?.label ?? t}</span>)}
                {Object.entries(a.tools).map(([t, n]) => <span key={t} className="chip tool">{prettyTool(t)}{n > 1 ? ` ×${n}` : ""}</span>)}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
