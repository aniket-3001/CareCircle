import { X } from 'lucide-react';
import { useEffect, useRef, type ReactNode } from 'react';

/** A sheet on the native <dialog> element (focus trap, Escape to close and the backdrop come from the browser). */
export function Sheet({ open, title, onClose, children }: { open: boolean; title: string; onClose: () => void; children: ReactNode }): React.JSX.Element {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);
  return (
    <dialog ref={ref} className="sheet" aria-labelledby="sheet-title" onClose={onClose} onClick={(e) => e.target === ref.current && onClose()}>
      <header className="sheet__header">
        <h2 id="sheet-title">{title}</h2>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
          <X size={20} strokeWidth={1.75} aria-hidden="true" />
        </button>
      </header>
      <div className="sheet__body">{open ? children : null}</div>
    </dialog>
  );
}
