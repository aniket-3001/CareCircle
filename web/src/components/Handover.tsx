import { NotebookPen } from 'lucide-react';
import { useState } from 'react';
import { Async } from './Async';
import { useToast } from './Toast';
import { ago, nameOf, productName, title } from '../lib/format';
import { tr } from '../lib/i18n';
import { useApp, useLoad } from '../state';

/** Notes from one carer to the next. Append-only: a note is never edited, so what was handed over is what was said. A note can be about one entry and addressed to one
 *  named carer, who accepts it; it is marked when the entry it is about has changed since. */
export function Handover(): React.JSX.Element {
  const app = useApp();
  const toast = useToast();
  const notes = useLoad((a) => a.api.handovers(), [app.rev]);
  const people = useLoad((a) => a.api.people(), [app.rev]);
  const reg = useLoad((a) => a.api.regimen(), [app.rev]);
  const [text, setText] = useState('');
  const [to, setTo] = useState('');
  const [about, setAbout] = useState('');
  const [busy, setBusy] = useState(false);
  const me = (people.data?.you ?? '').toLowerCase();
  const others = (people.data?.carers ?? []).filter((c) => c.toLowerCase() !== me);

  async function add(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    setBusy(true);
    try { await app.api.handover(text, about, to); setText(''); setTo(''); setAbout(''); app.bump(); } catch (err) { toast(err instanceof Error ? err.message : 'Could not save'); } finally { setBusy(false); }
  }
  async function accept(id: string): Promise<void> {
    try {
      const r = await app.api.acceptHandover(id);
      toast(r.warning ?? 'Accepted.');
      app.bump();
    } catch (err) { toast(err instanceof Error ? err.message : 'Could not accept'); }
  }
  return (
    <section className="card" aria-labelledby="hand-title" data-testid="handover">
      <div className="card-head"><h2 id="hand-title">{tr('Handover notes')}</h2><NotebookPen size={20} aria-hidden="true" /></div>
      <form className="stack" onSubmit={add}>
        <input type="text" aria-label={tr('Write a note for the next carer')} placeholder={tr('Write a note for the next carer')} value={text} onChange={(e) => setText(e.target.value)} maxLength={400} />
        <div className="row row--wrap row--end">
          <label className="field">{tr('About')}
            <select value={about} onChange={(e) => setAbout(e.target.value)} data-testid="handover-about">
              <option value="">{tr('Nothing in particular')}</option>
              {(reg.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.product ? productName(r.product) : title(r.drug)}{r.product ? ` (${title(r.drug)})` : ''} {r.dose_text}</option>)}
            </select>
          </label>
          <label className="field">{tr('For')}
            <select value={to} onChange={(e) => setTo(e.target.value)} data-testid="handover-to">
              <option value="">{tr('Whoever is next')}</option>
              {others.map((c) => <option key={c} value={c}>{nameOf(c)}</option>)}
            </select>
          </label>
          <button type="submit" className="btn btn--sm" disabled={busy || !text.trim()} data-testid="handover-add">{tr('Add note')}</button>
        </div>
      </form>
      <Async state={notes}>
        {(rows) => rows.length === 0 ? <p className="muted">{tr('No notes yet.')}</p> : (
          <div className="rows">{rows.slice(0, 6).map((n) => (
            <div key={n.id} className="item" data-testid="handover-row" data-status={n.status}>
              <div>
                <div className="item__title">{n.text}</div>
                <div className="item__sub">
                  {nameOf(n.by)}, {ago(n.at, app.now())}
                  {n.to ? <> · {tr('for')} {nameOf(n.to)}</> : null}
                  {n.about_drug ? <> · {tr('regarding')} {title(n.about_drug)}</> : null}
                  {n.status === 'accepted' ? <> · {tr('accepted by')} {nameOf(n.accepted_by ?? '')}</> : n.to ? <> · {tr('waiting to be accepted')}</> : null}
                  {n.stale ? <> · <b>{tr('the entry has changed since')}</b></> : null}
                </div>
              </div>
              {n.status === 'open' && n.for_me && (
                <button type="button" className="btn btn--sm" onClick={() => void accept(n.id)} data-testid="handover-accept">{tr('Accept')}</button>
              )}
            </div>
          ))}</div>
        )}
      </Async>
      <p className="muted small">{tr('A note cannot be edited or removed once saved: add another to correct it.')}</p>
    </section>
  );
}
