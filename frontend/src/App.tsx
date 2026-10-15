import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { AgentCards } from "./components/AgentCards";
import { ApprovalCards } from "./components/ApprovalCard";
import { Conversation } from "./components/Conversation";
import { RunSummary } from "./components/RunSummary";
import { SkyHeader } from "./components/SkyHeader";
import { TicketList } from "./components/TicketList";
import { Timeline } from "./components/Timeline";
import { API_BASE, POLL_IDLE_MS, POLL_RUNNING_MS } from "./config";
import { milestones, phaseFor, progress, sunPosition } from "./sky";
import type { Approval, BoardEvent, Cash, RunState, RunSummary as Summary, Ticket } from "./types";

const RUNS_KEY = "runIdByTicket";

// A link like /?ticket=101&run=<run_id> opens that ticket and shows that run (used for shareable views).
const params = new URLSearchParams(window.location.search);
const LINK_TICKET = params.get("ticket") ? Number(params.get("ticket")) : null;
const LINK_RUN = params.get("run");

export default function App() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [shopDate, setShopDate] = useState<string | null>(null);
  const [cash, setCash] = useState<Cash | null>(null);
  const [run, setRun] = useState<RunState | null>(null);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [selected, setSelected] = useState<number | null>(LINK_TICKET);
  const [runIdByTicket, setRunIdByTicket] = useState<Record<number, string>>(() => {
    const saved: Record<number, string> = JSON.parse(localStorage.getItem(RUNS_KEY) ?? "{}");
    return LINK_TICKET !== null && LINK_RUN ? { ...saved, [LINK_TICKET]: LINK_RUN } : saved;
  });
  const [events, setEvents] = useState<BoardEvent[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [offline, setOffline] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const viewRunId = selected !== null ? runIdByTicket[selected] ?? null : null;
  const lastIndex = useRef<{ runId: string | null; index: number | undefined }>({ runId: null, index: undefined });

  useEffect(() => localStorage.setItem(RUNS_KEY, JSON.stringify(runIdByTicket)), [runIdByTicket]);

  const flash = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 7000);
  };

  // One refresh of everything the board shows.
  const refresh = useCallback(async () => {
    try {
      const [t, c, r, a] = await Promise.all([api.tickets(), api.cash(), api.currentRun(), api.approvals()]);
      setTickets(t.tickets);
      setShopDate(t.shop_date);
      setCash(c);
      setRun(r);
      setApprovals(a);
      setOffline(null);
      if (r.run_id && r.ticket_id !== null) {
        setRunIdByTicket((m) => (m[r.ticket_id!] === r.run_id ? m : { ...m, [r.ticket_id!]: r.run_id! }));
      }
      setSelected((s) => s ?? r.ticket_id ?? t.tickets[0]?.id ?? null);
    } catch (e) {
      setOffline(e instanceof ApiError && e.status === 0 ? e.message : String(e));
    }
  }, []);

  // Fetch new events for the run being viewed (only what's new since last time).
  const refreshEvents = useCallback(async (runId: string | null) => {
    if (!runId) {
      setEvents([]);
      lastIndex.current = { runId: null, index: undefined };
      return;
    }
    const fresh = lastIndex.current.runId !== runId;
    const res = await api.events(runId, fresh ? undefined : lastIndex.current.index);
    lastIndex.current = { runId, index: res.last_index };
    setEvents((prev) => (fresh ? res.events : [...prev, ...res.events]));
  }, []);

  const running = run?.status === "running";

  // Poll: quickly while a ticket runs, slowly otherwise.
  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const loop = async () => {
      await refresh();
      await refreshEvents(viewRunId).catch(() => undefined);
      if (!stop) timer = setTimeout(loop, running ? POLL_RUNNING_MS : POLL_IDLE_MS);
    };
    loop();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [refresh, refreshEvents, viewRunId, running]);

  // When the viewed run is finished, load the per-agent summary.
  const viewedRunActive = running && run?.run_id === viewRunId;
  useEffect(() => {
    setSummary(null);
    if (!viewRunId || viewedRunActive) return;
    api.summary(viewRunId).then(setSummary).catch(() => setSummary(null));
  }, [viewRunId, viewedRunActive]);

  const startRun = async (id: number) => {
    try {
      const r = await api.runTicket(id);
      setRunIdByTicket((m) => ({ ...m, [id]: r.run_id }));
      lastIndex.current = { runId: null, index: undefined };
      setEvents([]);
      setSummary(null);
      await refresh();
    } catch (e) {
      flash(e instanceof Error ? e.message : String(e));
    }
  };

  const decide = async (id: number, approve: boolean, name: string, note: string) => {
    try {
      if (approve) {
        const res = await api.approve(id, name, note);
        flash(res.checking_balance !== undefined ? `Paid. Checking is now $${res.checking_balance.toFixed(2)}.` : "Approved.");
      } else {
        await api.reject(id, name, note);
        flash("Rejected. Nothing was paid or ordered.");
      }
    } catch (e) {
      flash(e instanceof Error ? e.message : String(e));
    }
    await refresh();
  };

  const reset = async () => {
    if (!window.confirm("Reset the shop data to the original values? Payments, approvals, drafts and ticket updates are cleared (the audit trail is kept).")) return;
    try {
      await api.reset();
      setRunIdByTicket({});
      setEvents([]);
      setSummary(null);
      lastIndex.current = { runId: null, index: undefined };
      flash("Fresh start: the shop is back to its original values.");
      await refresh();
    } catch (e) {
      flash(e instanceof Error ? e.message : String(e));
    }
  };

  // The run shown on the desk: the live run if it is the selected ticket's, else that ticket's last (finished) run.
  const viewedRun: RunState | null = !viewRunId
    ? null
    : run?.run_id === viewRunId
      ? run
      : { run_id: viewRunId, ticket_id: selected, status: "completed", error: null, started_at: null,
          finished_at: null, report: null, usage: null, waiting_for_approval: null };
  const steps = useMemo(() => milestones(events, viewedRun), [events, viewedRun]);
  const phase = phaseFor(viewedRun, steps, tickets);
  const sun = sunPosition(phase, progress(steps));
  const ticket = tickets.find((t) => t.id === selected) ?? null;

  return (
    <div className="app" data-phase={phase}>
      <SkyHeader phase={phase} sun={sun} shopDate={shopDate} cash={cash} demo={!!run?.demo_mode} />
      {offline && (
        <div className="banner">
          {offline}. Start it from the <code>backend/</code> folder with <code>uvicorn main:app --reload --port 8000</code>
          {" "}(the board calls <code>{API_BASE}</code>).
        </div>
      )}
      {toast && <div className="toast" role="status">{toast}</div>}
      <main className="layout">
        <TicketList
          tickets={tickets}
          selected={selected}
          runningTicket={running ? run?.ticket_id ?? null : null}
          onSelect={setSelected}
          onRun={startRun}
          onReset={reset}
          busy={running}
        />
        <div className="workspace">
          {ticket && (
            <section className="ticket-hero">
              <div>
                <span className="ticket-id">#{ticket.id}</span>
                <h2>{ticket.subject}</h2>
                <p>{ticket.requester} · {ticket.status.replace(/_/g, " ")}</p>
              </div>
              {ticket.state === "resolved" && <span className="resolved-stamp">Resolved</span>}
              {viewRunId && <Timeline steps={steps} />}
              {run?.status === "error" && run.run_id === viewRunId && <p className="run-error">Run stopped: {run.error}</p>}
            </section>
          )}
          <ApprovalCards approvals={approvals} pausedOn={run?.waiting_for_approval?.approval_id ?? null}
            balance={cash?.balance ?? null} onDecide={decide} />
          <AgentCards events={events} run={viewedRun} />
          <Conversation events={events} running={!!viewedRunActive} />
          {summary && <RunSummary summary={summary} />}
        </div>
      </main>
    </div>
  );
}
