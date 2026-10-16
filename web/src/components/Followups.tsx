import { ListChecks } from 'lucide-react';
import { useState } from 'react';
import { Async } from './Async';
import { useToast } from './Toast';
import { ago, nameOf } from '../lib/format';
import { tr } from '../lib/i18n';
import type { FollowupSuggestion } from '../api/types';
import { useApp, useLoad } from '../state';

/** A short checklist drawn from the record. The record suggests; nothing is written until a person ticks it. It asks and tells; it never says what to take. */
export function Followups(): React.JSX.Element {
  const app = useApp();
  const toast = useToast();
  const list = useLoad((a) => a.api.followups(), [app.rev]);
  const [sug, setSug] = useState<FollowupSuggestion[] | null>(null);
  const [pick, setPick] = useState<Set<string>>(new Set());

  const fail = (e: unknown): void => toast(e instanceof Error ? e.message : 'Could not save');
  async function suggest(): Promise<void> {
    try {
      const s = await app.api.followupSuggest(app.now());
      setSug(s); setPick(new Set(s.map((x) => x.key)));
    } catch (e) { fail(e); }
  }
  async function approve(): Promise<void> {
    try { await app.api.followupAdd(sug!.filter((x) => pick.has(x.key))); setSug(null); app.bump(); } catch (e) { fail(e); }
  }
  async function done(id: string, dismiss: boolean): Promise<void> {
    try { await app.api.followupDone(id, dismiss); app.bump(); } catch (e) { fail(e); }
  }
  const toggle = (k: string): void => setPick((p) => { const n = new Set(p); if (n.has(k)) n.delete(k); else n.add(k); return n; });

  return (
    <section className="card" aria-labelledby="fu-title" data-testid="followups">
      <div className="card-head"><h2 id="fu-title">{tr('Follow-ups')}</h2><ListChecks size={20} aria-hidden="true" /></div>
      <p className="muted small">{tr('Things to ask or tell, drawn from the record. You choose which to keep.')}</p>
      {sug === null ? (
        <button type="button" className="btn btn--soft btn--sm" style={{ justifySelf: 'start' }} onClick={() => void suggest()} data-testid="fu-suggest">{tr('Suggest from the record')}</button>
      ) : sug.length === 0 ? (
        <p className="muted" data-testid="fu-none">{tr('Nothing new to suggest.')} <button type="button" className="btn btn--ghost btn--sm" onClick={() => setSug(null)}>{tr('Close')}</button></p>
      ) : (
        <div className="rows" data-testid="fu-suggestions">
          {sug.map((s) => (
            <label key={s.key} className="item" style={{ cursor: 'pointer' }}>
              <input type="checkbox" checked={pick.has(s.key)} onChange={() => toggle(s.key)} />
              <div><div className="item__title">{s.text}</div></div>
            </label>
          ))}
          <div className="row">
            <button type="button" className="btn btn--sm" disabled={pick.size === 0} onClick={() => void approve()} data-testid="fu-approve">{tr('Add the ticked ones')}</button>
            <button type="button" className="btn btn--ghost btn--sm" onClick={() => setSug(null)}>{tr('Cancel')}</button>
          </div>
        </div>
      )}
      <Async state={list}>
        {(rows) => rows.length === 0 ? null : (
          <div className="rows">
            {rows.map((f) => (
              <div key={f.id} className="item" data-testid="followup">
                <div>
                  <div className="item__title" style={f.status === 'done' ? { textDecoration: 'line-through', opacity: 0.7 } : undefined}>{f.text}</div>
                  <div className="item__sub">
                    {f.status === 'done' ? `${tr('Done by')} ${nameOf(f.done_by ?? '')}, ${ago(f.done_at ?? f.at, app.now())}` : `${tr('Added by')} ${nameOf(f.by)}, ${ago(f.at, app.now())}`}
                    {f.stale && <> · <strong>{tr('The record has changed since: look again first')}</strong></>}
                  </div>
                </div>
                {f.status === 'open' && (
                  <div className="row">
                    <button type="button" className="btn btn--soft btn--sm" onClick={() => void done(f.id, false)}>{tr('Done')}</button>
                    <button type="button" className="btn btn--ghost btn--sm" onClick={() => void done(f.id, true)}>{tr('Dismiss')}</button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </Async>
    </section>
  );
}
