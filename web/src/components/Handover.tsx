import { NotebookPen } from 'lucide-react';
import { useState } from 'react';
import { Async } from './Async';
import { useToast } from './Toast';
import { ago, nameOf } from '../lib/format';
import { tr } from '../lib/i18n';
import { useApp, useLoad } from '../state';

/** Notes from one carer to the next. Append-only: a note is never edited, so what was handed over is what was said. */
export function Handover(): React.JSX.Element {
  const app = useApp();
  const toast = useToast();
  const notes = useLoad((a) => a.api.handovers(), [app.rev]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);

  async function add(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    setBusy(true);
    try { await app.api.handover(text); setText(''); app.bump(); } catch (err) { toast(err instanceof Error ? err.message : 'Could not save'); } finally { setBusy(false); }
  }
  return (
    <section className="card" aria-labelledby="hand-title" data-testid="handover">
      <div className="card-head"><h2 id="hand-title">{tr('Handover notes')}</h2><NotebookPen size={20} aria-hidden="true" /></div>
      <form className="row" onSubmit={add}>
        <input type="text" aria-label={tr('Write a note for the next carer')} placeholder={tr('Write a note for the next carer')} value={text} onChange={(e) => setText(e.target.value)} maxLength={400} />
        <button type="submit" className="btn btn--sm" disabled={busy || !text.trim()}>{tr('Add note')}</button>
      </form>
      <Async state={notes}>
        {(rows) => rows.length === 0 ? <p className="muted">{tr('No notes yet.')}</p> : (
          <div className="rows">{rows.slice(0, 6).map((n) => <div key={n.id} className="item"><div><div className="item__title">{n.text}</div><div className="item__sub">{nameOf(n.by)}, {ago(n.at, app.now())}</div></div></div>)}</div>
        )}
      </Async>
      <p className="muted small">{tr('A note cannot be edited or removed once saved: add another to correct it.')}</p>
    </section>
  );
}
