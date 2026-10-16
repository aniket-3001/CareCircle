import { CalendarDays, ClipboardList, Pencil, Printer, X } from 'lucide-react';
import { useState } from 'react';
import type { Appointment, Visit } from '../api/types';
import { Async } from './Async';
import { Pill, Spinner } from './Pill';
import { Sheet } from './Sheet';
import { useToast } from './Toast';
import { ago, nameOf, title } from '../lib/format';
import { useApp, useLoad } from '../state';
import { tr } from '../lib/i18n';

const when = (ms: number) => new Date(ms).toLocaleString(undefined, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
const localInput = (ms: number) => { const d = new Date(ms - new Date(ms).getTimezoneOffset() * 60000); return d.toISOString().slice(0, 16); };

/** Appointments with who goes and what to bring, and a one-page "what to bring" assembled from the record. A past appointment reads as done and stays in the history. */
export function Appointments(): React.JSX.Element {
  const app = useApp();
  const toast = useToast();
  const list = useLoad((a) => a.api.appointments(a.now()), [app.rev]);
  const members = useLoad((a) => a.api.people(), [app.rev]);
  const [name, setName] = useState('');
  const [at, setAt] = useState(localInput(Date.now() + 3 * 86_400_000));
  const [place, setPlace] = useState('');
  const [who, setWho] = useState('');
  const [bring, setBring] = useState('');
  const [busy, setBusy] = useState(false);
  const [visit, setVisit] = useState<Visit | null>(null);
  const [opening, setOpening] = useState(false);
  const [editing, setEditing] = useState<Appointment | null>(null);
  const [ef, setEf] = useState({ title: '', at: '', place: '', who: '', bring: '' });

  async function add(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    setBusy(true);
    try {
      await app.api.appoint(name, new Date(at).getTime(), place, who, bring);
      setName(''); setPlace(''); setBring('');
      toast('Appointment saved');
      app.bump();
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Could not save');
    } finally { setBusy(false); }
  }
  async function prepare(a?: Appointment): Promise<void> {
    setOpening(true);
    setVisit(null);
    try { setVisit(await app.api.visit(a?.id ?? '', app.now())); } catch (err) { toast(err instanceof Error ? err.message : 'Could not prepare'); setOpening(false); }
  }
  const startEdit = (a: Appointment): void => { setEf({ title: a.title, at: localInput(a.at), place: a.place, who: a.who, bring: a.bring }); setEditing(a); };
  async function saveEdit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    try {
      await app.api.editAppointment(editing!.id, { ...ef, at: new Date(ef.at).getTime() });
      setEditing(null); toast('Appointment updated'); app.bump();
    } catch (err) { toast(err instanceof Error ? err.message : 'Could not save'); }
  }
  const carers = members.data?.carers ?? [];

  return (
    <section className="card" aria-labelledby="appt-title" data-testid="appointments">
      <div className="card-head"><h2 id="appt-title">{tr('Appointments')}</h2><CalendarDays size={20} aria-hidden="true" /></div>
      <form className="grid-2" onSubmit={add}>
        <label className="field">{tr('What')}<input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. INR check at the clinic" required maxLength={80} /></label>
        <label className="field">{tr('When')}<input type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} required /></label>
        <label className="field">{tr('Where')}<input type="text" value={place} onChange={(e) => setPlace(e.target.value)} maxLength={100} /></label>
        <label className="field">{tr('Who goes')}
          <select value={who} onChange={(e) => setWho(e.target.value)}><option value="">not decided</option>{carers.map((c) => <option key={c} value={c}>{nameOf(c)}</option>)}</select>
        </label>
        <label className="field" style={{ gridColumn: '1 / -1' }}>{tr('What to bring')}<input type="text" value={bring} onChange={(e) => setBring(e.target.value)} placeholder="e.g. INR diary, every pill box" maxLength={200} /></label>
        <div className="row"><button type="submit" className="btn btn--sm" disabled={busy || !name.trim()}>{tr('Add appointment')}</button>{busy && <Spinner />}</div>
      </form>
      <Async state={list}>
        {(rows) => rows.length === 0 ? <p className="muted">{tr('No appointments yet.')}</p> : (
          <div className="rows">
            {rows.slice(0, 6).map((a) => (
              <div key={a.id} className="item">
                <div>
                  <div className="item__title">{a.title} <Pill tone={a.status === 'upcoming' ? 'info' : 'mute'}>{a.status}</Pill></div>
                  <div className="item__sub">{when(a.at)}{a.place ? `, ${a.place}` : ''}{a.who ? `, ${nameOf(a.who)} goes` : ''}</div>
                  {a.bring && <div className="item__sub">Bring: {a.bring}</div>}
                </div>
                <div className="row">
                  {a.status === 'upcoming' && <button type="button" className="btn btn--ghost btn--sm" onClick={() => void prepare(a)}><ClipboardList size={16} aria-hidden="true" /> {tr('What to bring')}</button>}
                  {a.status === 'upcoming' && <button type="button" className="icon-btn" aria-label={`Edit ${a.title}`} onClick={() => startEdit(a)} data-testid="edit-appt"><Pencil size={16} aria-hidden="true" /></button>}
                  {a.status === 'upcoming' && <button type="button" className="icon-btn" aria-label={`Cancel ${a.title}`} onClick={() => void app.api.cancelAppointment(a.id).then(() => { toast('Cancelled'); app.bump(); })}><X size={16} aria-hidden="true" /></button>}
                </div>
              </div>
            ))}
          </div>
        )}
      </Async>
      <button type="button" className="btn btn--soft btn--sm" style={{ justifySelf: 'start' }} onClick={() => void prepare()}><ClipboardList size={16} aria-hidden="true" /> {tr('Prepare for the next visit')}</button>
      <Sheet open={editing !== null} title={tr('Edit appointment')} onClose={() => setEditing(null)}>
        <form className="stack" onSubmit={(e) => void saveEdit(e)} data-testid="edit-appt-form">
          <label className="field">{tr('What')}<input type="text" value={ef.title} onChange={(e) => setEf({ ...ef, title: e.target.value })} required maxLength={80} /></label>
          <label className="field">{tr('When')}<input type="datetime-local" value={ef.at} onChange={(e) => setEf({ ...ef, at: e.target.value })} required /></label>
          <label className="field">{tr('Where')}<input type="text" value={ef.place} onChange={(e) => setEf({ ...ef, place: e.target.value })} maxLength={100} /></label>
          <label className="field">{tr('Who goes')}
            <select value={ef.who} onChange={(e) => setEf({ ...ef, who: e.target.value })}><option value="">not decided</option>{carers.map((c) => <option key={c} value={c}>{nameOf(c)}</option>)}</select>
          </label>
          <label className="field">{tr('What to bring')}<input type="text" value={ef.bring} onChange={(e) => setEf({ ...ef, bring: e.target.value })} maxLength={200} /></label>
          <button type="submit" className="btn" disabled={!ef.title.trim()}>{tr('Save changes')}</button>
        </form>
      </Sheet>
      <Sheet open={opening} title={tr('What to bring to the visit')} onClose={() => setOpening(false)}>
        {!visit ? <Spinner /> : (
          <div className="stack" data-testid="visit">
            <p className="muted">{visit.appointment ? `${visit.appointment.title}, ${when(visit.appointment.at)}.` : 'No appointment is planned, so this covers the last 30 days.'} Changes since {when(visit.since)}.</p>
            <h3>{tr('Changed on record')}</h3>
            {visit.changes.length === 0 ? <p className="muted">{tr('No changes in that time.')}</p> : <ul className="steps">{visit.changes.map((c, i) => <li key={i}><span><b>{title(c.drug)}</b>: {c.action === 'stop' ? 'recorded as stopped' : `${c.dose_text} ${c.freq_text}`.trim()} ({nameOf(c.by)}, {ago(c.at, app.now())})</span></li>)}</ul>}
            <h3>{tr('On record now')}</h3>
            <p>{visit.regimen.map((r) => `${title(r.drug)} ${r.dose_text} ${r.freq_text}`.trim()).join('; ') || 'Nothing.'}</p>
            {visit.flags.length > 0 && (<><h3>{tr('What the sources flag')}</h3><ul className="steps">{visit.flags.map((f, i) => <li key={i}><span>{f.drugs ? `${title(f.drugs[0])} + ${title(f.drugs[1])} (${f.level})` : f.path} <span className="muted">· {f.source}</span></span></li>)}</ul></>)}
            {visit.allergy_hits.length > 0 && (<><h3>{tr('Allergies recorded')}</h3><ul className="steps">{visit.allergy_hits.map((h, i) => <li key={i}><span>{h.allergy}: {title(h.drug)} is {h.why}. Ask the prescriber.</span></li>)}</ul></>)}
            {visit.readings.length > 0 && (<><h3>{tr('Readings in that time')}</h3><p>{visit.readings.map((r) => `${r.kind.replace('_', ' ')} ${r.value} ${r.unit}`).join('; ')}</p></>)}
            {Object.keys(visit.unseen).length > 0 && (<><h3>{tr('Not yet seen by every carer')}</h3><ul className="steps">{Object.entries(visit.unseen).map(([c, u]) => <li key={c}><span>{nameOf(c)}: {u.map((x) => title(x.drug)).join(', ')}</span></li>)}</ul></>)}
            <p className="muted small">{visit.note}</p>
            <button type="button" className="btn btn--soft btn--sm no-print" style={{ justifySelf: 'start' }} onClick={() => window.print()}><Printer size={16} aria-hidden="true" /> {tr('Print')}</button>
          </div>
        )}
      </Sheet>
    </section>
  );
}
