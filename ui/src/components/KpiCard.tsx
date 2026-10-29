import type { ReactNode } from "react";

export function KpiCard({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="panel px-4 py-3">
      <div className="text-xs text-ink-muted">{label}</div>
      <div className="num mt-1 text-[22px] leading-7 font-semibold tracking-tight">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-ink-faint">{hint}</div>}
    </div>
  );
}
