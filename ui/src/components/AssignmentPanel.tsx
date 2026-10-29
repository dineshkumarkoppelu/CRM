import type { AssignmentResult, Recommendation } from "../api/types";
import { formatPct } from "../lib/format";
import { FitTypeBadge, RecStatus, ScoreBar } from "./Badges";
import { RepLink } from "./Links";
import { ReasonText } from "./ReasonText";

/** Engine result for one deal: who got it and why, the ranked candidates, and who was skipped.
 *  Used after creating a deal, on the deal page, and for previews. */
export function AssignmentPanel({
  result,
  onOverride,
  overridingId,
  preview = false,
}: {
  result: AssignmentResult;
  onOverride?: (repId: string) => void;
  overridingId?: string | null;
  preview?: boolean;
}) {
  const top = result.candidates.find((c) => c.status === "ASSIGNED") ?? (preview ? result.candidates[0] : undefined);
  return (
    <div className="space-y-4">
      <Summary result={result} top={top} preview={preview} />

      {result.candidates.length > 0 && (
        <div>
          <h3 className="mb-1.5 text-xs font-medium text-ink-muted">Ranked candidates</h3>
          <div className="panel overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th className="w-10">#</th>
                  <th>Sales person</th>
                  <th>Fit</th>
                  <th className="text-right">Fit value</th>
                  <th className="text-right">Availability</th>
                  <th>Score</th>
                  <th>Status</th>
                  {onOverride && <th />}
                </tr>
              </thead>
              <tbody>
                {result.candidates.map((c) => (
                  <CandidateRow
                    key={c.sales_person_id}
                    c={c}
                    onOverride={onOverride}
                    busy={overridingId === c.sales_person_id}
                    disabled={Boolean(overridingId)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {result.unavailable.length > 0 && (
        <div>
          <h3 className="mb-1.5 text-xs font-medium text-ink-muted">Not considered</h3>
          <div className="flex flex-wrap gap-1.5">
            {result.unavailable.map((u) => (
              <span key={u.id} className="inline-flex items-center gap-2 rounded-sm border border-line bg-panel px-2 py-1 text-xs">
                <RepLink id={u.id} name={u.name} />
                <span className={u.reason === "AT_CAPACITY" ? "text-lost" : "text-ink-muted"}>
                  {u.reason === "AT_CAPACITY" ? `At capacity ${u.open_count}/${u.capacity}` : "Inactive"}
                </span>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Summary({ result, top, preview }: { result: AssignmentResult; top?: Recommendation; preview: boolean }) {
  if (!top) {
    const tone =
      result.assignment_status === "UNASSIGNED" ? "border-warn/30 bg-warn-soft text-warn" : "border-line bg-canvas text-ink";
    return (
      <div className={`rounded border px-3.5 py-3 text-[13px] ${tone}`}>
        {result.assignment_status === "UNASSIGNED" && <div className="font-medium">Unassigned</div>}
        {result.assignment_status === "MANUAL" && <div className="font-medium">Manual assignment</div>}
        <div className={result.assignment_status === "UNASSIGNED" ? "" : "text-ink-muted"}>{result.message}</div>
      </div>
    );
  }
  const label = preview ? "Would assign to" : result.assignment_status === "MANUAL" ? "Owner" : "Assigned to";
  return (
    <div className="rounded border border-accent/25 bg-accent-soft/50 px-3.5 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <span className="text-xs text-ink-muted">{label}</span>
        <span className="text-[15px] font-semibold">
          <RepLink id={top.sales_person_id} name={top.name} />
        </span>
        <FitTypeBadge fitType={top.fit_type} />
        <span className="ml-auto">
          <ScoreBar value={top.score} width={96} />
        </span>
      </div>
      <div className="mt-1.5">
        <ReasonText reason={top.reason} />
      </div>
      {preview && <div className="mt-2 text-xs text-ink-faint">Preview only. Nothing has been saved.</div>}
    </div>
  );
}

function CandidateRow({
  c,
  onOverride,
  busy,
  disabled,
}: {
  c: Recommendation;
  onOverride?: (repId: string) => void;
  busy: boolean;
  disabled: boolean;
}) {
  return (
    <tr className={c.status === "ASSIGNED" ? "bg-won-soft/40" : ""}>
      <td className="num text-ink-muted" title={c.rank === 0 ? "Added by a manual override" : undefined}>
        {c.rank === 0 ? "—" : c.rank}
      </td>
      <td className="max-w-[300px]">
        <div className="font-medium">
          <RepLink id={c.sales_person_id} name={c.name} />
        </div>
        <ReasonText reason={c.reason} className="block text-xs" />
      </td>
      <td>
        <FitTypeBadge fitType={c.fit_type} />
      </td>
      <td className="num text-right">{formatPct(c.fit)}</td>
      <td className="num text-right">{formatPct(c.availability)}</td>
      <td>
        <ScoreBar value={c.score} width={56} />
      </td>
      <td>
        <RecStatus status={c.status} />
      </td>
      {onOverride && (
        <td className="text-right">
          {c.status !== "ASSIGNED" && (
            <button type="button" className="btn btn-sm" disabled={disabled} onClick={() => onOverride(c.sales_person_id)}>
              {busy ? "Assigning…" : "Assign instead"}
            </button>
          )}
        </td>
      )}
    </tr>
  );
}
