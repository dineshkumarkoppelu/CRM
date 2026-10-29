// Number and date formatting for India (en-IN: ₹, lakh/crore grouping).

const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const integer = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const oneDecimal = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const twoDecimals = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** ₹12,34,000 */
export const formatINR = (value: number | null | undefined): string => (value == null ? "—" : inr.format(value));

/** ₹12.3 L / ₹1.35 Cr / ₹45,000 - for KPI cards and chart axes. */
export function formatINRCompact(value: number | null | undefined): string {
  if (value == null) return "—";
  const abs = Math.abs(value);
  if (abs >= 1e7) return `₹${twoDecimals.format(value / 1e7)} Cr`;
  if (abs >= 1e5) return `₹${oneDecimal.format(value / 1e5)} L`;
  return inr.format(value);
}

export const formatInt = (value: number | null | undefined): string => (value == null ? "—" : integer.format(value));
export const formatDecimal = (value: number | null | undefined, digits = 2): string =>
  value == null ? "—" : value.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });

/** 0.673 -> "67%". Whole percentages everywhere (half-up). */
export function formatPct(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${Math.round(value * 100 + 1e-9)}%`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-10-06" -> "6 Oct 2026" (parsed as a plain date, no time zone shift). */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

/** "2026-10" -> "Oct 2026"; short = "Oct 26" */
export function formatMonth(ym: string, short = false): string {
  const [y, m] = ym.split("-").map(Number);
  return short ? `${MONTHS[m - 1]} ${String(y).slice(2)}` : `${MONTHS[m - 1]} ${y}`;
}

export function titleCase(value: string): string {
  return value
    .toLowerCase()
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export const SIZE_LABEL: Record<string, string> = { SMB: "SMB", MID_MARKET: "Mid-market", ENTERPRISE: "Enterprise" };
