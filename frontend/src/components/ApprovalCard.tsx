import { useState } from "react";
import { money } from "../agents";
import type { Approval } from "../types";

const KIND: Record<Approval["kind"], string> = {
  invoice_payment: "Pay a vendor invoice",
  rent_payment: "Pay rent",
  purchase_order: "Place a purchase order",
};

interface Props {
  approvals: Approval[];
  pausedOn: number | null;
  balance: number | null;
  onDecide: (id: number, approve: boolean, name: string, note: string) => Promise<void>;
}

export function ApprovalCards({ approvals, pausedOn, balance, onDecide }: Props) {
  const [name, setName] = useState(() => localStorage.getItem("approverName") ?? "");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<number | null>(null);
  if (!approvals.length) return null;

  const decide = async (id: number, approve: boolean) => {
    localStorage.setItem("approverName", name.trim());
    setBusy(id);
    try {
      await onDecide(id, approve, name.trim(), note.trim());
      setNote("");
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="approvals" aria-label="Waiting for your approval">
      {approvals.map((a) => {
        const d = a.details as Record<string, string | number>;
        const isPay = a.kind !== "purchase_order";
        const after = balance !== null && isPay ? balance - a.amount : null;
        return (
          <article key={a.id} className={`approval ${a.id === pausedOn ? "paused" : ""}`}>
            <div className="approval-head">
              <span className="approval-kicker">{a.id === pausedOn ? "The team is waiting on you" : "Waiting for a decision"}</span>
              <h2>{KIND[a.kind]} · {money(a.amount)}</h2>
            </div>
            <dl className="approval-facts">
              {isPay ? (
                <>
                  <div><dt>Pay to</dt><dd>{String(d.payee ?? "—")}</dd></div>
                  <div><dt>Due</dt><dd>{String(d.due_date ?? "—")} ({Number(d.days_until_due) < 0 ? `${-Number(d.days_until_due)} days overdue` : `in ${d.days_until_due} days`})</dd></div>
                  <div><dt>Checking after</dt><dd className={after !== null && after < 0 ? "bad" : ""}>{after !== null ? money(after) : "—"}</dd></div>
                </>
              ) : (
                <>
                  <div><dt>Order</dt><dd>{d.qty} × {String(d.sku)} ({String(d.size)}) from {String(d.vendor_name)}</dd></div>
                  <div><dt>Arrives</dt><dd>{String(d.expected_arrival)}</dd></div>
                  <div><dt>Cash today</dt><dd>{money(Number(d.cash_on_hand ?? 0))}{Number(d.cash_shortfall) > 0 ? ` · short ${money(Number(d.cash_shortfall))}` : ""}</dd></div>
                </>
              )}
            </dl>
            <p className="approval-reason"><strong>{a.requested_by}:</strong> {a.reason}</p>
            <p className="approval-note">
              {isPay ? "Approving pays this now and lowers checking." : "Approving records the order. No cash moves until the vendor invoices."}
            </p>
            <div className="approval-form">
              <label>Your name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Meg" /></label>
              <label>Note (optional)<input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Shown to the agent" /></label>
              <div className="approval-buttons">
                <button className="btn approve" disabled={!name.trim() || busy !== null} onClick={() => decide(a.id, true)}>
                  {busy === a.id ? "…" : isPay ? `Approve and pay ${money(a.amount)}` : "Approve order"}
                </button>
                <button className="btn reject" disabled={!name.trim() || busy !== null} onClick={() => decide(a.id, false)}>
                  Reject
                </button>
              </div>
            </div>
          </article>
        );
      })}
    </section>
  );
}
