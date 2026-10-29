import type { DealStatus, Domain, FitType, RecommendationStatus, Stage } from "../api/types";
import { domainColor, STAGE_LABEL } from "../lib/domains";

export function DomainChip({ domain, muted = false }: { domain: Domain; muted?: boolean }) {
  const color = domainColor(domain);
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-sm px-1.5 py-0.5 text-xs ${
        muted ? "text-ink-muted" : "text-ink"
      }`}
      style={{ backgroundColor: `${color}14`, boxShadow: `inset 0 0 0 1px ${color}33` }}
    >
      <span className="h-2 w-2 rounded-[2px]" style={{ backgroundColor: color }} />
      {domain}
    </span>
  );
}

const STATUS_STYLE: Record<DealStatus, string> = {
  OPEN: "bg-open-soft text-open",
  WON: "bg-won-soft text-won",
  LOST: "bg-lost-soft text-lost",
};

export function StatusBadge({ status }: { status: DealStatus }) {
  return (
    <span className={`inline-block rounded-sm px-1.5 py-0.5 text-[11px] font-semibold tracking-wide ${STATUS_STYLE[status]}`}>
      {status}
    </span>
  );
}

export function StageLabel({ stage }: { stage: Stage }) {
  const index = ["LEAD", "QUALIFIED", "PROPOSAL", "NEGOTIATION"].indexOf(stage);
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-[13px]">
      <span className="inline-flex gap-0.5" aria-hidden>
        {[0, 1, 2, 3].map((i) => (
          <span key={i} className={`h-2.5 w-1 rounded-[1px] ${i <= index ? "bg-accent" : "bg-line-strong"}`} />
        ))}
      </span>
      {STAGE_LABEL[stage]}
    </span>
  );
}

const FIT_STYLE: Record<FitType, string> = {
  DIRECT: "border-accent/40 text-accent bg-accent-soft",
  PEER: "border-d-iot/40 text-d-iot bg-d-iot/5",
  RELATED: "border-d-devops/40 text-d-devops bg-d-devops/5",
  COLD_START: "border-line-strong text-ink-muted bg-canvas",
};

const FIT_LABEL: Record<FitType, string> = { DIRECT: "Direct", PEER: "Peer", RELATED: "Related domain", COLD_START: "Cold start" };

export function FitTypeBadge({ fitType }: { fitType: FitType }) {
  return (
    <span className={`inline-block whitespace-nowrap rounded-sm border px-1.5 py-px text-[11px] font-medium ${FIT_STYLE[fitType]}`}>
      {FIT_LABEL[fitType]}
    </span>
  );
}

const REC_STYLE: Record<RecommendationStatus, string> = {
  ASSIGNED: "text-won",
  CANDIDATE: "text-ink-muted",
  OVERRIDDEN: "text-warn line-through decoration-1",
};

export function RecStatus({ status }: { status: RecommendationStatus }) {
  return <span className={`text-xs font-medium ${REC_STYLE[status]}`}>{status.charAt(0) + status.slice(1).toLowerCase()}</span>;
}

/** Horizontal bar 0..1 with the numeric value next to it. */
export function ScoreBar({ value, width = 72, digits = 3 }: { value: number; width?: number; digits?: number }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <span className="inline-flex items-center gap-2">
      <span className="relative h-1.5 rounded-full bg-line" style={{ width }}>
        <span className="absolute inset-y-0 left-0 rounded-full bg-accent" style={{ width: `${pct}%` }} />
      </span>
      <span className="num text-[13px] tabular-nums">{value.toFixed(digits)}</span>
    </span>
  );
}

/** Open deals vs capacity, e.g. 6/8 with a small gauge; red when full. */
export function LoadGauge({ open, capacity }: { open: number; capacity: number }) {
  const full = open >= capacity;
  const pct = capacity > 0 ? Math.min(1, open / capacity) * 100 : 100;
  return (
    <span className="inline-flex items-center gap-2">
      <span className="relative h-1.5 w-12 rounded-full bg-line">
        <span
          className={`absolute inset-y-0 left-0 rounded-full ${full ? "bg-lost" : "bg-ink-faint"}`}
          style={{ width: `${pct}%` }}
        />
      </span>
      <span className={`num text-[13px] ${full ? "font-medium text-lost" : ""}`}>
        {open}/{capacity}
      </span>
    </span>
  );
}
