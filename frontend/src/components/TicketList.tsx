import type { Ticket } from "../types";

const TYPE_LABEL: Record<string, string> = {
  customer_order: "Customer order",
  rent_notice: "Rent notice",
  price_override: "Price override",
};

const STATUS_LABEL: Record<string, string> = {
  open: "Open",
  in_progress: "In progress",
  waiting_on_human: "Waiting on you",
  waiting_on_vendor: "Waiting on vendor",
  resolved: "Resolved",
};

interface Props {
  tickets: Ticket[];
  selected: number | null;
  runningTicket: number | null;
  onSelect: (id: number) => void;
  onRun: (id: number) => void;
  onReset: () => void;
  busy: boolean;
}

export function TicketList({ tickets, selected, runningTicket, onSelect, onRun, onReset, busy }: Props) {
  const resolved = tickets.filter((t) => t.state === "resolved").length;
  return (
    <aside className="tickets">
      <div className="panel-head">
        <h2>Tickets</h2>
        <span className="count">{resolved} of {tickets.length} resolved</span>
      </div>
      <ul>
        {tickets.map((t) => {
          const isSel = t.id === selected;
          const isRunning = t.id === runningTicket;
          return (
            <li key={t.id}>
              <button
                className={`ticket ${isSel ? "selected" : ""} ${t.state}`}
                onClick={() => onSelect(t.id)}
                aria-pressed={isSel}
              >
                <span className="ticket-top">
                  <span className="ticket-id">#{t.id}</span>
                  <span className={`pill status-${t.status}`}>
                    {t.state === "resolved" && <span aria-hidden="true">✓ </span>}
                    {isRunning ? "Running…" : STATUS_LABEL[t.status] ?? t.status}
                  </span>
                </span>
                <span className="ticket-subject">{t.subject}</span>
                <span className="ticket-meta">{TYPE_LABEL[t.type] ?? t.type} · {t.requester}</span>
              </button>
              {isSel && (
                <button className="btn primary run" onClick={() => onRun(t.id)} disabled={busy}>
                  {isRunning ? "Team at work…" : t.state === "resolved" ? "Run the team again" : "Start the team on this ticket"}
                </button>
              )}
            </li>
          );
        })}
      </ul>
      <button className="btn ghost reset" onClick={onReset} disabled={busy}>
        Fresh start · reset the shop data
      </button>
    </aside>
  );
}
