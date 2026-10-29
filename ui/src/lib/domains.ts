import type { DealStatus, Domain, Stage } from "../api/types";

export const STAGES: Stage[] = ["LEAD", "QUALIFIED", "PROPOSAL", "NEGOTIATION"];

/** Built-in domain colours (mirror --color-d-* in index.css). */
const BUILTIN_COLOR: Record<string, string> = {
  AI: "#6a55c9",
  Cybersecurity: "#c0462b",
  IoT: "#10857a",
  DevOps: "#b07a14",
  "Cloud Migration": "#3577b8",
};

/**
 * Muted colours for domains added at runtime; picked by a stable hash of the name.
 * Hues are kept away from the built-ins so a new domain never looks like an existing one.
 */
const EXTRA_COLORS = ["#b0567c", "#5e8c31", "#7c7a2e", "#8c6239", "#56627a", "#a33d9a"];

/** The colour of a domain, the same everywhere (chips, charts, graph). */
export function domainColor(domain: Domain): string {
  const fixed = BUILTIN_COLOR[domain];
  if (fixed) return fixed;
  let hash = 0;
  for (const ch of domain.toLowerCase()) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return EXTRA_COLORS[hash % EXTRA_COLORS.length];
}

/** Stage shades: one hue, darker as the deal progresses. */
export const STAGE_COLOR: Record<Stage, string> = {
  LEAD: "#c9d3e1",
  QUALIFIED: "#93a8c6",
  PROPOSAL: "#5c7aa6",
  NEGOTIATION: "#2c4a78",
};

export const STATUS_COLOR: Record<DealStatus, string> = {
  OPEN: "#44607f",
  WON: "#2f7d4f",
  LOST: "#b42318",
};

export const STAGE_LABEL: Record<Stage, string> = {
  LEAD: "Lead",
  QUALIFIED: "Qualified",
  PROPOSAL: "Proposal",
  NEGOTIATION: "Negotiation",
};

export const ACCENT = "#1f4f99";
export const INK_MUTED = "#5b6474";
export const LINE = "#e3e6eb";
