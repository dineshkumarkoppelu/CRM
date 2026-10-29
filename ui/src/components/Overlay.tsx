import { useEffect, useRef, type ReactNode } from "react";

function useEscape(open: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);
}

export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  danger = false,
  busy = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  useEscape(open && !busy, onCancel);
  useEffect(() => {
    if (open) cancelRef.current?.focus();
  }, [open]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/30 p-4">
      <div role="dialog" aria-modal="true" aria-labelledby="confirm-title" className="w-full max-w-md rounded-md bg-panel shadow-lg">
        <div className="border-b border-line px-5 py-3.5">
          <h2 id="confirm-title" className="text-[15px] font-semibold">
            {title}
          </h2>
        </div>
        <div className="px-5 py-4 text-[13px] leading-relaxed text-ink-muted">{children}</div>
        <div className="flex justify-end gap-2 border-t border-line bg-canvas/50 px-5 py-3">
          <button ref={cancelRef} type="button" className="btn" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button type="button" className={`btn ${danger ? "btn-danger" : "btn-primary"}`} onClick={onConfirm} disabled={busy}>
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export function Drawer({
  open,
  title,
  subtitle,
  width = 720,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  subtitle?: string;
  width?: number;
  onClose: () => void;
  children: ReactNode;
}) {
  useEscape(open, onClose);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-ink/20">
      <button type="button" aria-label="Close" className="flex-1 cursor-default" onClick={onClose} />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="flex h-full flex-col border-l border-line bg-panel shadow-xl"
        style={{ width: `min(${width}px, 100vw)` }}
      >
        <header className="flex items-start justify-between border-b border-line px-5 py-3.5">
          <div>
            <h2 className="text-[15px] font-semibold">{title}</h2>
            {subtitle && <p className="mt-0.5 text-xs text-ink-muted">{subtitle}</p>}
          </div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
            Close
          </button>
        </header>
        <div className="flex-1 overflow-y-auto">{children}</div>
      </aside>
    </div>
  );
}

/** Small hover/focus popover for secondary explanations (e.g. back-test limitations). */
export function InfoTip({ label, children, align = "right" }: { label: string; children: ReactNode; align?: "left" | "right" }) {
  return (
    <span className="group relative inline-flex">
      <button type="button" className="text-xs text-ink-muted underline decoration-dotted underline-offset-2 hover:text-ink">
        {label}
      </button>
      <span
        role="tooltip"
        className={`invisible absolute top-full z-20 mt-1 w-72 rounded border border-line bg-panel p-2.5 text-xs leading-relaxed text-ink-muted shadow-md group-focus-within:visible group-hover:visible ${
          align === "right" ? "right-0" : "left-0"
        }`}
      >
        {children}
      </span>
    </span>
  );
}
