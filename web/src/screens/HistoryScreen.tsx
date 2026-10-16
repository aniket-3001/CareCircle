import { Download, Printer, RotateCcw, ShieldCheck, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { Async } from '../components/Async';
import { Hero } from '../components/Hero';
import { PageHead } from '../components/PageHead';
import { Pill } from '../components/Pill';
import { Segmented } from '../components/Segmented';
import { Sheet } from '../components/Sheet';
import type { TimelineEvent } from '../api/types';
import { useToast } from '../components/Toast';
import { Flags } from '../components/Flags';
import { nameOf, plural, title, when } from '../lib/format';
import { useApp, useLoad } from '../state';
import { tr } from '../lib/i18n';

export function HistoryScreen(): React.JSX.Element {
  const app = useApp();
  const toast = useToast();
  const tl = useLoad((a) => a.api.timeline(a.now()));
  const [q, setQ] = useState('');
  const [kind, setKind] = useState<'all' | 'record' | 'ack' | 'give'>('all');
  const receipts = useLoad((a) => a.api.receipts());
  const me = useLoad((a) => a.api.me());
  const isOwner = !!me.data?.tenants[app.session.circle]?.includes('admin');      // only the owner can erase for good; the server enforces it too
  const [mistake, setMistake] = useState<string | null>(null);
  const [asOf, setAsOf] = useState<number | null>(null);
  const [forgetting, setForgetting] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  const [erase, setErase] = useState(false);
  const [typed, setTyped] = useState('');

  const t = app.now();
  const first = tl.data?.length ? Math.min(...tl.data.map((e) => e.at)) - 60_000 : t - 3_600_000;
  const at = asOf ?? t;
  const past = useLoad((a) => a.api.check(asOf ?? undefined), [asOf]);

  async function doMistake(): Promise<void> {
    if (!mistake) return;
    try {
      await app.api.markMistake(mistake, reason);
      toast('Marked as entered by mistake. It stays in the history.');
      setMistake(null); setReason('');
      app.bump();
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not mark it');
    }
  }

  async function restore(id: string): Promise<void> {
    try {
      await app.api.restoreEntry(id);
      toast('Put back on the record.');
      app.bump();
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not put it back');
    }
  }

  async function doForget(): Promise<void> {
    if (!forgetting) return;
    try {
      const r = await app.api.forget(forgetting, reason);
      toast(`Removed for good. Receipt ${r.receipt}.`);
      setForgetting(null); setReason('');
      app.bump();
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not remove it');
    }
  }

  const shown = (events: TimelineEvent[]): TimelineEvent[] => {
    const needle = q.trim().toLowerCase();
    return events.filter((e) => (kind === 'all' || (kind === 'record' ? e.kind === 'record' || e.kind === 'stop' : e.kind === kind))
      && (!needle || `${e.text} ${e.who} ${e.quote}`.toLowerCase().includes(needle)));
  };

  async function exportFhir(): Promise<void> {
    const b = await app.api.fhir();
    const url = URL.createObjectURL(new Blob([JSON.stringify(b, null, 2)], { type: 'application/fhir+json' }));
    const a = document.createElement('a');
    a.href = url; a.download = `${app.session.person}-medications-fhir.json`; a.click();
    URL.revokeObjectURL(url);
    toast(`Exported ${b.entry.length - 1} medication statements (FHIR R4, free text)`);
  }

  async function doErase(): Promise<void> {
    try {
      const r = await app.api.forgetPerson(typed);
      toast(`All records of ${title(app.session.person)} removed (${r.removed_entries} entries). Receipt ${r.receipt}.`);
      setErase(false); setTyped('');
      app.bump();
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not remove');
    }
  }

  return (
    <div className="screen">
      <PageHead crumb={tr('The record over time')} title={tr('What did we know, and when?')} lede={tr('Nothing is overwritten: each change closes the one before it, so you can look back at any moment.')} />
      <div className="layout">
        <div className="col">
          <section className="card" aria-labelledby="asof-title">
            <div className="card-head">
              <h2 id="asof-title">{tr('Look back in time')}</h2>
              <Pill tone="info">{asOf === null ? 'now' : when(asOf)}</Pill>
            </div>
            <input className="range" type="range" aria-label={tr('Point in time')} min={first} max={t} step={60_000} value={at} onChange={(e) => setAsOf(Number(e.target.value) >= t - 60_000 ? null : Number(e.target.value))} />
            <Async state={past}>
              {(c) => (
                <>
                  <Hero check={c} chips={[{ Icon: ShieldCheck, text: plural(c.regimen.length, 'medicine') }, { Icon: ShieldCheck, text: asOf === null ? 'now' : when(asOf) }, { Icon: ShieldCheck, text: 'as recorded' }]} />
                  <div className="rows">
                    {c.regimen.length ? c.regimen.map((r) => (
                      <div key={r.id} className="item"><div><div className="item__title">{title(r.drug)} <span className="muted">{r.dose_text} {r.freq_text}</span></div><div className="item__sub">added by {nameOf(r.by)}</div></div></div>
                    )) : <p className="muted">{tr('Nothing on record at that time.')}</p>}
                  </div>
                </>
              )}
            </Async>
          </section>
          <section className="card" aria-labelledby="data-title">
            <h2 id="data-title">{tr('Your data')}</h2>
            <p className="muted">{tr('Take the regimen with you, or remove it. Removing leaves only a receipt: a hash of what was removed, who did it and when.')}</p>
            <div className="row row--wrap">
              <button type="button" className="btn btn--soft" onClick={() => void exportFhir()}><Download size={18} aria-hidden="true" /> {tr('Export as FHIR (JSON)')}</button>
              <button type="button" className="btn btn--soft" onClick={() => window.print()}><Printer size={18} aria-hidden="true" /> {tr('Print a summary')}</button>
              {isOwner && <button type="button" className="btn btn--soft" style={{ color: 'var(--danger)' }} onClick={() => setErase(true)}><Trash2 size={18} aria-hidden="true" /> Remove everything about {title(app.session.person)}</button>}
            </div>
            <Async state={receipts}>
              {(r) => (r.length > 0 && (
                <div className="rows">
                  <p className="eyebrow">{tr('Receipts')}</p>
                  {r.map((x) => (
                    <div key={x.receipt} className="item"><div><div className="item__title">{x.receipt} <Pill>{x.kind}</Pill></div><div className="item__sub">{nameOf(x.by)} · {x.when} · removed {x.removed}</div><code>{x.sha256}</code></div></div>
                  ))}
                </div>
              ))}
            </Async>
          </section>
        </div>
        <div className="col">
          <Async state={tl}>
            {(events) => (
              <section className="card" aria-labelledby="tl-title">
                <h2 id="tl-title">{tr('Everything that happened')}</h2>
                {events.length === 0 ? <p className="muted">{tr('Nothing recorded yet.')}</p> : (
                  <>
                  <div className="stack">
                    <label className="field"><span className="sr-only">{tr('Search the history')}</span>
                      <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={tr('Search the history, e.g. warfarin or Meena')} data-testid="history-search" />
                    </label>
                    <Segmented<'all' | 'record' | 'ack' | 'give'> name="hkind" label={tr('Kind')} value={kind} onChange={setKind}
                      options={[{ value: 'all', label: tr('All') }, { value: 'record', label: tr('Changes') }, { value: 'ack', label: tr('Seen') }, { value: 'give', label: tr('Given') }]} />
                  </div>
                  {shown(events).length === 0 && <p className="muted" data-testid="history-none">{tr('Nothing matches.')}</p>}
                  <ol className="timeline">
                    {shown(events).map((e, i) => (
                      <li key={`${e.at}-${i}`} data-kind={e.kind}>
                        <div>{e.text}</div>
                        {e.quote && <div className="item__sub">“{e.quote}”</div>}
                        <div className="item__sub">{e.when} · {e.ago}</div>
                        {(e.kind === 'record' || e.kind === 'stop') && e.dose && e.status === 'mistake' && (
                          <button type="button" className="btn btn--ghost btn--sm" style={{ paddingInline: 0 }} onClick={() => void restore(e.dose!)}><RotateCcw size={14} aria-hidden="true" /> {tr('Put it back')}</button>
                        )}
                        {(e.kind === 'record' || e.kind === 'stop') && e.dose && e.status !== 'mistake' && (
                          <button type="button" className="btn btn--ghost btn--sm" style={{ paddingInline: 0 }} onClick={() => setMistake(e.dose!)} data-testid="mark-mistake">{tr('Entered by mistake')}</button>
                        )}
                        {isOwner && (e.kind === 'record' || e.kind === 'stop') && e.dose && (
                          <button type="button" className="btn btn--ghost btn--sm" style={{ color: 'var(--danger)', paddingInline: 0, marginLeft: 12 }} onClick={() => setForgetting(e.dose!)}>{tr('Remove for good')}</button>
                        )}
                      </li>
                    ))}
                  </ol>
                  </>
                )}
              </section>
            )}
          </Async>
        </div>
      </div>

      <PrintSummary />
      <Sheet open={forgetting !== null} title={tr('Remove this entry for good?')} onClose={() => setForgetting(null)}>
        <p>{tr('Its medicine, dose, quoted line, links and acknowledgements are deleted from the graph and cannot be brought back. A receipt with a hash of what was removed stays.')}</p>
        <label className="field">{tr('Reason (optional)')}<input type="text" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. entered by mistake" /></label>
        <button type="button" className="btn btn--danger" onClick={() => void doForget()}>{tr('Remove for good')}</button>
      </Sheet>
      <Sheet open={mistake !== null} title={tr('Mark this entry as entered by mistake?')} onClose={() => setMistake(null)}>
        <p>{tr('It comes off the current record and the entry before it counts again. It stays in the history, marked, with your name, and the owner or you can put it back.')}</p>
        <label className="field">{tr('Reason (optional)')}<input type="text" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. should have been 4 mg" /></label>
        <button type="button" className="btn" onClick={() => void doMistake()}>{tr('Mark as entered by mistake')}</button>
      </Sheet>
      <Sheet open={erase} title={`Remove everything about ${title(app.session.person)}?`} onClose={() => setErase(false)}>
        <p>{tr('Every entry, dose record and reminder about this person is deleted. Type their name to confirm.')}</p>
        <label className="field">Type “{app.session.person}”<input type="text" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" /></label>
        <button type="button" className="btn btn--danger" disabled={typed.trim().toLowerCase() !== app.session.person.toLowerCase()} onClick={() => void doErase()}>{tr('Remove everything')}</button>
      </Sheet>
    </div>
  );
}

/** Shown only when printing: one page a carer can hand to a pharmacist or doctor. It is the record as it stands, with its sources, and says plainly that it is not advice. */
function PrintSummary(): React.JSX.Element {
  const app = useApp();
  const now = useLoad((a) => a.api.check());
  return (
    <div className="print-only" aria-hidden="true">
      <h1>Medicines on record for {title(app.session.person)}</h1>
      <p>Prepared {new Date().toLocaleString()} by Care Circle{app.profile ? ` for ${app.profile.name}` : ''}. This is a list of what carers recorded, checked against public interaction data. It is not medical advice and not a prescription.</p>
      {now.data && (
        <>
          <h2>{tr('Medicines')}</h2>
          <ul>{now.data.regimen.map((r) => <li key={r.id}><b>{title(r.drug)}</b> {r.dose_text} {r.freq_text} (recorded by {nameOf(r.by)}, {r.source})</li>)}</ul>
          <h2>{tr('What the sources list for these medicines')}</h2>
          <Flags check={now.data} />
          <p>{now.data.notice}</p>
        </>
      )}
    </div>
  );
}
