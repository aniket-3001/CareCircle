import { UserRoundCheck } from 'lucide-react';
import { useState } from 'react';
import { Async } from './Async';
import { useToast } from './Toast';
import { nameOf, title, whenLocal } from '../lib/format';
import { useT } from '../lib/i18n';
import { useApp, useLoad } from '../state';

const WHO = ['the person themselves', 'a guardian or family member on their behalf'];

/** A note of whether the person knows about this record, and a plain read-only view of what it holds, written for them. A note, not legal consent. */
export function Consent(): React.JSX.Element {
  const app = useApp();
  const t = useT();
  const toast = useToast();
  const c = useLoad((a) => a.api.consent(), [app.rev]);
  const [view, setView] = useState(false);
  const pv = useLoad((a) => (view ? a.api.patientView() : Promise.resolve(null)), [view, app.rev]);
  const [status, setStatus] = useState('agreed');
  const [who, setWho] = useState(WHO[0]);
  const [note, setNote] = useState('');

  async function save(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    try { await app.api.setConsent(status, who, note); setNote(''); app.bump(); toast(t('Saved.')); } catch (err) { toast(err instanceof Error ? err.message : 'Could not save'); }
  }

  return (
    <details className="card inspect" data-testid="consent">
      <summary><UserRoundCheck size={18} aria-hidden="true" /> {title(app.session.person)}: {t('does the person know about this record?')}</summary>
      <Async state={c}>
        {(r) => (
          <>
            <p data-testid="consent-status">
              {r.current ? `${t(r.status === 'agreed' ? 'Noted as agreed' : r.status === 'declined' ? 'Noted as declined' : 'Not asked yet')} · ${t(r.current.who)} · ${nameOf(r.current.by)} · ${whenLocal(r.current.at)}${r.current.note ? ` · “${r.current.note}”` : ''}` : t('Not asked yet')}
            </p>
            <form className="grid-2" onSubmit={save}>
              <label className="field">{t('Their answer')}
                <select value={status} onChange={(e) => setStatus(e.target.value)} data-testid="consent-answer">
                  <option value="agreed">{t('Agreed')}</option><option value="declined">{t('Declined')}</option><option value="not_asked">{t('Not asked yet')}</option>
                </select>
              </label>
              <label className="field">{t('Who answered')}
                <select value={who} onChange={(e) => setWho(e.target.value)}>{WHO.map((w) => <option key={w} value={w}>{t(w)}</option>)}</select>
              </label>
              <label className="field">{t('Note (optional)')}<input type="text" maxLength={200} value={note} onChange={(e) => setNote(e.target.value)} /></label>
              <div className="row"><button type="submit" className="btn btn--sm" data-testid="consent-save">{t('Write it down')}</button>
                <button type="button" className="btn btn--soft btn--sm" onClick={() => setView(!view)} data-testid="patient-view-toggle">{view ? t('Hide their view') : t('Show what they would read')}</button></div>
            </form>
            <p className="muted small">{t(r.note)}</p>
          </>
        )}
      </Async>
      {view && (
        <Async state={pv}>
          {(v) => v ? (
            <div data-testid="patient-view" className="stack">
              <h3>{t('What this record holds about you')}</h3>
              <ul className="plain">{v.medicines.map((m) => <li key={m.drug}>{title(m.drug)} {m.dose_text} {m.freq_text}</li>)}</ul>
              <p><b>{t('Who can see it')}:</b> {v.who_can_see.map(nameOf).join(', ')}</p>
              <ul className="plain">{v.what_is_kept.map((x) => <li key={x}>{x}</li>)}</ul>
              <ul className="plain muted">{v.what_is_not.map((x) => <li key={x}>{x}</li>)}</ul>
              <p className="muted">{v.your_rights}</p>
            </div>
          ) : null}
        </Async>
      )}
    </details>
  );
}

