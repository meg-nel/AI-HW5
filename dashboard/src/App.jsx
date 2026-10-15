import React, { useCallback, useEffect, useMemo, useState } from "react";

const api = (path, opts = {}) =>
  fetch(path, { headers: { "Content-Type": "application/json" }, ...opts }).then((r) => {
    if (!r.ok) throw new Error(`${r.status} ${path}`);
    return r.json();
  });

// ---------- live event stream ----------
function useEventStream() {
  const [events, setEvents] = useState([]);
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    let ws, retry, closed = false;
    const connect = () => {
      ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
      ws.onopen = () => { setConnected(true); setEvents([]); };
      ws.onmessage = (m) => setEvents((prev) => [...prev, JSON.parse(m.data)].slice(-1000));
      ws.onclose = () => { setConnected(false); if (!closed) retry = setTimeout(connect, 2000); };
    };
    connect();
    return () => { closed = true; clearTimeout(retry); ws?.close(); };
  }, []);
  return { events, connected };
}

// ---------- agent mesh ----------
function AgentMesh({ agents, statuses, recentEdges }) {
  const size = 320, r = 115, c = size / 2;
  const pos = Object.fromEntries(
    agents.map((a, i) => {
      const t = (2 * Math.PI * i) / agents.length - Math.PI / 2;
      return [a.id, { x: c + r * Math.cos(t), y: c + r * Math.sin(t) }];
    })
  );
  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="mesh">
      {agents.flatMap((a, i) =>
        agents.slice(i + 1).map((b) => {
          const hot = recentEdges.has(`${a.id}|${b.id}`) || recentEdges.has(`${b.id}|${a.id}`);
          return (
            <line key={a.id + b.id} x1={pos[a.id].x} y1={pos[a.id].y} x2={pos[b.id].x} y2={pos[b.id].y}
              className={hot ? "edge hot" : "edge"} />
          );
        })
      )}
      {agents.map((a) => {
        const s = statuses[a.id] || "idle";
        return (
          <g key={a.id} transform={`translate(${pos[a.id].x},${pos[a.id].y})`}>
            <circle r="26" fill={a.color} className={`node ${s}`} />
            <text y="44" textAnchor="middle" className="node-label">{a.name}</text>
            <text y="4" textAnchor="middle" className="node-status">{s === "waiting_approval" ? "⏸" : s === "working" ? "●" : ""}</text>
          </g>
        );
      })}
    </svg>
  );
}

// ---------- activity feed ----------
const describe = (e, names) => {
  const n = (id) => names[id] || id;
  switch (e.type) {
    case "task_started": return [`New task for ${n(e.agent)}`, e.prompt];
    case "task_finished": return [`Task ${e.status}`, e.result];
    case "agent_started": return [`${n(e.agent)} started${e.delegated_by ? ` (from ${n(e.delegated_by)})` : ""}`, null];
    case "thinking": return [`${n(e.agent)} is thinking`, e.text];
    case "message": return [`${n(e.agent)}`, e.text];
    case "tool_call": return [`${n(e.agent)} → ${e.tool}`, JSON.stringify(e.input, null, 2)];
    case "tool_result": return [`${e.tool} ${e.error ? "failed" : "returned"}`, e.output];
    case "delegation": return [`${n(e.from_agent)} delegated to ${n(e.to_agent)}`, e.brief];
    case "delegation_result": return [`${n(e.from_agent)} reported back to ${n(e.to_agent)}`, e.result];
    case "approval_requested": return [`${n(e.agent)} needs approval #${e.approval_id}`, e.summary];
    case "approval_decided": return [`Approval #${e.approval_id} ${e.approved ? "approved" : "rejected"}`, e.note];
    case "draft_created": return [`${n(e.agent)} added draft #${e.draft_id} to the board`, null];
    case "agent_error": return [`${n(e.agent)} hit an error`, e.error];
    default: return null;
  }
};

function Feed({ events, agents, taskFilter }) {
  const names = Object.fromEntries(agents.map((a) => [a.id, a.name]));
  const colors = Object.fromEntries(agents.map((a) => [a.id, a.color]));
  const rows = events
    .filter((e) => !taskFilter || e.task_id === taskFilter)
    .map((e) => ({ e, d: describe(e, names) }))
    .filter((x) => x.d)
    .reverse();
  return (
    <div className="feed">
      {rows.length === 0 && <p className="muted">No activity yet. Give the team a task.</p>}
      {rows.map(({ e, d: [title, body] }) => (
        <div key={e.id} className={`feed-row ${e.type}`} style={{ borderLeftColor: colors[e.agent || e.from_agent] || "#555" }}>
          <div className="feed-head">
            <span>{title}</span>
            <span className="muted">{e.ts.slice(11, 19)} · {e.task_id}</span>
          </div>
          {body && <pre className="feed-body">{body}</pre>}
        </div>
      ))}
    </div>
  );
}

// ---------- approvals ----------
function Approvals({ approvals, onDecide }) {
  const pending = approvals.filter((a) => a.status === "pending");
  const [notes, setNotes] = useState({});
  return (
    <div>
      {pending.length === 0 && <p className="muted">Nothing waiting on you.</p>}
      {pending.map((a) => (
        <div key={a.id} className="card approval">
          <div className="card-head"><b>#{a.id} · {a.kind}</b><span className="muted">{a.requested_by}</span></div>
          <p>{a.summary}</p>
          {a.payload && a.payload !== "{}" && <pre className="feed-body">{a.payload}</pre>}
          <input placeholder="Note to the agent (optional)" value={notes[a.id] || ""}
            onChange={(e) => setNotes({ ...notes, [a.id]: e.target.value })} />
          <div className="row">
            <button className="approve" onClick={() => onDecide(a.id, true, notes[a.id] || "")}>Approve</button>
            <button className="reject" onClick={() => onDecide(a.id, false, notes[a.id] || "")}>Reject</button>
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------- drafts board ----------
function Drafts({ drafts, onStatus }) {
  const visible = drafts.filter((d) => d.status !== "discarded");
  return (
    <div>
      <p className="banner">Drafts are never sent. Nothing here reaches a customer or vendor.</p>
      {visible.length === 0 && <p className="muted">No drafts yet.</p>}
      {visible.map((d) => (
        <details key={d.id} className="card draft">
          <summary>
            <span className={`tag ${d.kind}`}>{d.kind === "customer_email" ? "Customer email" : "Vendor request"}</span>
            <b>{d.subject}</b>
            <span className="muted"> → {d.recipient} · by {d.author_agent} · {d.status}</span>
          </summary>
          <pre className="feed-body">{d.body}</pre>
          <div className="row">
            <button onClick={() => onStatus(d.id, "reviewed")}>Mark reviewed</button>
            <button className="reject" onClick={() => onStatus(d.id, "discarded")}>Discard</button>
          </div>
        </details>
      ))}
    </div>
  );
}

// ---------- shop data ----------
function ShopTables({ orders, inventory }) {
  return (
    <div className="tables">
      <table>
        <thead><tr><th>Order</th><th>Customer</th><th>Items</th><th>Status</th><th>Due</th></tr></thead>
        <tbody>{orders.map((o) => (
          <tr key={o.id}><td>{o.id}</td><td>{o.customer_id}</td>
            <td>{o.items.map((i) => `${i.qty}× ${i.sku}`).join(", ")}</td>
            <td><span className={`status ${o.status}`}>{o.status}</span></td><td>{o.due_date}</td></tr>
        ))}</tbody>
      </table>
      <table>
        <thead><tr><th>SKU</th><th>Product</th><th>Stock</th><th>Reorder at</th></tr></thead>
        <tbody>{inventory.map((p) => (
          <tr key={p.sku} className={p.stock <= p.reorder_point ? "low" : ""}>
            <td>{p.sku}</td><td>{p.name}</td><td>{p.stock}</td><td>{p.reorder_point}</td></tr>
        ))}</tbody>
      </table>
    </div>
  );
}

export default function App() {
  const { events, connected } = useEventStream();
  const [agents, setAgents] = useState([]);
  const [approvals, setApprovals] = useState([]);
  const [drafts, setDrafts] = useState([]);
  const [orders, setOrders] = useState([]);
  const [inventory, setInventory] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [taskFilter, setTaskFilter] = useState("");
  const [prompt, setPrompt] = useState("");
  const [target, setTarget] = useState("ops_lead");
  const [tab, setTab] = useState("approvals");
  const [error, setError] = useState("");

  const refresh = useCallback(() => {
    Promise.all([api("/api/agents"), api("/api/approvals"), api("/api/drafts"), api("/api/orders"), api("/api/inventory"), api("/api/tasks")])
      .then(([a, ap, d, o, i, t]) => { setAgents(a); setApprovals(ap); setDrafts(d); setOrders(o); setInventory(i); setTasks(t); setError(""); })
      .catch((e) => setError(`Backend unreachable (${e.message}). Is uvicorn running on :8000?`));
  }, []);

  useEffect(refresh, [refresh]);
  // Refresh shop data whenever something that changes it happens
  const last = events[events.length - 1];
  useEffect(() => {
    if (last && ["approval_requested", "approval_decided", "draft_created", "tool_result", "task_started", "task_finished"].includes(last.type)) refresh();
  }, [last, refresh]);

  const statuses = useMemo(() => {
    const s = {};
    for (const e of events) if (e.type === "agent_status") s[e.agent] = e.status;
    return s;
  }, [events]);

  const recentEdges = useMemo(() => {
    const cutoff = Date.now() - 30_000;
    return new Set(events.filter((e) => e.type === "delegation" && Date.parse(e.ts) > cutoff).map((e) => `${e.from_agent}|${e.to_agent}`));
  }, [events]);

  const submit = async (e) => {
    e.preventDefault();
    if (!prompt.trim()) return;
    await api("/api/tasks", { method: "POST", body: JSON.stringify({ agent_id: target, prompt }) });
    setPrompt("");
  };
  const decide = (id, approved, note) =>
    api(`/api/approvals/${id}`, { method: "POST", body: JSON.stringify({ approved, note }) }).then(refresh);
  const setDraftStatus = (id, status) =>
    api(`/api/drafts/${id}`, { method: "POST", body: JSON.stringify({ status }) }).then(refresh);

  const pendingCount = approvals.filter((a) => a.status === "pending").length;

  return (
    <div className="app">
      <header>
        <h1>Campus Customs · Multi-Agent Ops</h1>
        <span className={connected ? "pill ok" : "pill bad"}>{connected ? "live" : "disconnected"}</span>
      </header>
      {error && <div className="error">{error}</div>}
      <main>
        <section className="col">
          <h2>Team</h2>
          <AgentMesh agents={agents} statuses={statuses} recentEdges={recentEdges} />
          <ul className="agent-list">
            {agents.map((a) => (
              <li key={a.id}><span className="dot" style={{ background: a.color }} /> <b>{a.name}</b>
                <span className="muted"> · {statuses[a.id] || "idle"}</span><div className="muted small">{a.role}</div></li>
            ))}
          </ul>
          <form onSubmit={submit} className="launcher">
            <h2>Assign a task</h2>
            <select value={target} onChange={(e) => setTarget(e.target.value)}>
              {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
            <textarea rows={4} value={prompt} onChange={(e) => setPrompt(e.target.value)}
              placeholder="e.g. Review all open orders and flag anything at risk for its due date." />
            <button type="submit">Send to agent</button>
          </form>
        </section>

        <section className="col wide">
          <div className="row between">
            <h2>Live activity</h2>
            <select value={taskFilter} onChange={(e) => setTaskFilter(e.target.value)}>
              <option value="">All tasks</option>
              {tasks.map((t) => <option key={t.id} value={t.id}>{t.id} · {t.status} · {t.prompt.slice(0, 40)}</option>)}
            </select>
          </div>
          <Feed events={events} agents={agents} taskFilter={taskFilter} />
        </section>

        <section className="col">
          <nav className="tabs">
            <button className={tab === "approvals" ? "on" : ""} onClick={() => setTab("approvals")}>Approvals{pendingCount ? ` (${pendingCount})` : ""}</button>
            <button className={tab === "drafts" ? "on" : ""} onClick={() => setTab("drafts")}>Drafts ({drafts.filter((d) => d.status === "draft").length})</button>
            <button className={tab === "shop" ? "on" : ""} onClick={() => setTab("shop")}>Shop</button>
          </nav>
          {tab === "approvals" && <Approvals approvals={approvals} onDecide={decide} />}
          {tab === "drafts" && <Drafts drafts={drafts} onStatus={setDraftStatus} />}
          {tab === "shop" && <ShopTables orders={orders} inventory={inventory} />}
        </section>
      </main>
    </div>
  );
}
