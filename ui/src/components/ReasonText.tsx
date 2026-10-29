/** The engine's reason sentence. The fit prefix ("PEER fit:", "Manual override:") is set apart
 *  and percentages are emphasised so the key numbers can be read at a glance. */
export function ReasonText({ reason, className = "" }: { reason: string; className?: string }) {
  const match = reason.match(/^((?:Manual override: )?(?:DIRECT fit:|PEER fit:|RELATED fit:|No domain history for [^:]+:))\s*(.*)$/);
  const prefix = match?.[1];
  const rest = match ? match[2] : reason;
  const parts = rest.split(/(\d+%|\d+\/\d+)/g);
  return (
    <span className={`text-[13px] leading-snug text-ink-muted ${className}`}>
      {prefix && <span className="font-medium text-ink">{prefix} </span>}
      {parts.map((part, i) =>
        /^(\d+%|\d+\/\d+)$/.test(part) ? (
          <span key={i} className="num font-medium text-ink">
            {part}
          </span>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </span>
  );
}
