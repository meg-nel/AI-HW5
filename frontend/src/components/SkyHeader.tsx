import { useEffect, useRef, useState } from "react";
import { money } from "../agents";
import { PHASE_LABEL, type Phase } from "../sky";
import type { Cash } from "../types";

interface Props {
  phase: Phase;
  sun: number; // 0..1 along the arc
  shopDate: string | null;
  cash: Cash | null;
  demo: boolean;
}

export function SkyHeader({ phase, sun, shopDate, cash, demo }: Props) {
  // Sun on a half-ellipse arc across the header.
  // At dawn and dusk the sun sits half below the horizon; at midday it rides high in the middle.
  const x = 3 + sun * 94;
  const y = 104 - Math.sin(sun * Math.PI) * 82;
  return (
    <header className="sky">
      <svg className="sky-arc" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        <path d="M2 104 Q50 -60 98 104" className="arc-path" />
      </svg>
      <div className="sun" style={{ left: `${x}%`, top: `${y}%` }} aria-hidden="true" />
      <div className="sky-inner">
        <div>
          <h1>Campus Customs · Agent Desk</h1>
          <p className="phase" aria-live="polite">{PHASE_LABEL[phase]}</p>
          <p className="meta">
            Shop date {shopDate ?? "…"} · five agents on gpt-6-luna{demo ? " · demo agents (no model calls)" : ""}
          </p>
        </div>
        <CashCard cash={cash} />
      </div>
    </header>
  );
}

function CashCard({ cash }: { cash: Cash | null }) {
  const prev = useRef<number | null>(null);
  const [delta, setDelta] = useState<number | null>(null);
  useEffect(() => {
    if (!cash) return;
    if (prev.current !== null && cash.balance !== prev.current) {
      setDelta(cash.balance - prev.current);
      const t = setTimeout(() => setDelta(null), 6000);
      prev.current = cash.balance;
      return () => clearTimeout(t);
    }
    prev.current = cash.balance;
  }, [cash]);

  return (
    <div className={`cash ${delta !== null ? (delta < 0 ? "cash-drop" : "cash-rise") : ""}`} aria-live="polite">
      <span className="cash-label">Checking</span>
      <span className="cash-balance">{cash ? money(cash.balance) : "—"}</span>
      {delta !== null && <span className="cash-delta">{delta < 0 ? "−" : "+"}{money(Math.abs(delta))}</span>}
      <span className="cash-sub">
        {cash ? `${money(cash.open_bills_total)} in open bills · as of ${cash.as_of}` : "loading"}
      </span>
    </div>
  );
}
