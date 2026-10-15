import { useEffect, useRef, type ReactNode } from 'react';

/** A bottom sheet on the native <dialog> element (focus trap, Escape to close and the backdrop come from the browser), as in Vayu's stats sheet. */
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
        <button type="button" className="button button--quiet" onClick={onClose}>
          Done
        </button>
      </header>
      <div className="sheet__body">{open ? children : null}</div>
    </dialog>
  );
}
