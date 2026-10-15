import type { Milestone } from "../sky";

export function Timeline({ steps }: { steps: Milestone[] }) {
  const next = steps.findIndex((s) => !s.done);
  return (
    <ol className="timeline" aria-label="Run progress">
      {steps.map((s, i) => (
        <li key={s.key} className={s.done ? "done" : i === next ? "current" : ""}>
          <span className="dot" aria-hidden="true">{s.done ? "✓" : ""}</span>
          <span className="label">{s.label}</span>
        </li>
      ))}
    </ol>
  );
}
