import { useState } from 'react';
import { Async } from '../components/Async';
import { Pill } from '../components/Pill';
import { Sheet } from '../components/Sheet';
import { useToast } from '../components/Toast';
import { Verdict } from '../components/Verdict';
import { nameOf, title, when } from '../lib/format';
import { useApp, useLoad } from '../state';

export function HistoryScreen(): React.JSX.Element {
  const app = useApp();
  const toast = useToast();
  const tl = useLoad((a) => a.api.timeline(a.now()));
  const receipts = useLoad((a) => a.api.receipts());
  const [asOf, setAsOf] = useState<number | null>(null);
  const [forgetting, setForgetting] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  const [erase, setErase] = useState(false);
  const [typed, setTyped] = useState('');

  const t = app.now();
  const first = tl.data?.length ? Math.min(...tl.data.map((e) => e.at)) - 60_000 : t - 3_600_000;
  const at = asOf ?? t;
  const past = useLoad((a) => a.api.check(asOf ?? undefined), [asOf]);

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
      <h1 className="headline">What did we know, and when?</h1>

      <section className="card" aria-labelledby="asof-title">
        <h2 className="card__title" id="asof-title">Look back in time</h2>
        <p className="muted">{asOf === null ? 'Now' : when(asOf)} · drag to see the regimen and the flags as they were then.</p>
        <input className="range" type="range" aria-label="Point in time" min={first} max={t} step={60_000} value={at} onChange={(e) => setAsOf(Number(e.target.value) >= t - 60_000 ? null : Number(e.target.value))} />
        <Async state={past}>
          {(c) => (
            <>
              <Verdict check={c} />
              <div className="rows">
                {c.regimen.length ? c.regimen.map((r) => (
                  <div key={r.id} className="item"><div><div className="item__title">{title(r.drug)} <span className="muted">{r.dose_text} {r.freq_text}</span></div><div className="item__sub">added by {nameOf(r.by)}</div></div></div>
                )) : <p className="muted">Nothing on record at that time.</p>}
              </div>
            </>
          )}
        </Async>
      </section>

      <Async state={tl}>
        {(events) => (
          <section className="card" aria-labelledby="tl-title">
            <h2 className="card__title" id="tl-title">Everything that happened</h2>
            {events.length === 0 ? <p className="muted">Nothing recorded yet.</p> : (
              <ol className="timeline">
                {events.map((e, i) => (
                  <li key={`${e.at}-${i}`} data-kind={e.kind}>
                    <div>{e.text}</div>
                    {e.quote && <div className="item__sub">“{e.quote}”</div>}
                    <div className="item__sub">{e.when} · {e.ago}</div>
                    {(e.kind === 'record' || e.kind === 'stop') && e.dose && (
                      <button type="button" className="button button--quiet button--small" style={{ color: 'var(--bad)', paddingInline: 0 }} onClick={() => setForgetting(e.dose!)}>Remove for good</button>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </section>
        )}
      </Async>

      <section className="card" aria-labelledby="data-title">
        <h2 className="card__title" id="data-title">Your data</h2>
        <p className="muted">Take the regimen with you, or remove it. Removing leaves only a receipt: a hash of what was removed, who did it and when.</p>
        <div className="row row--wrap">
          <button type="button" className="button button--secondary" onClick={() => void exportFhir()}>Export as FHIR (JSON)</button>
          <button type="button" className="button button--secondary" style={{ color: 'var(--bad)' }} onClick={() => setErase(true)}>Remove everything about {title(app.session.person)}</button>
        </div>
        <Async state={receipts}>
          {(r) => (r.length > 0 && (
            <div className="rows">
              <h3 className="section-title" style={{ marginTop: 'var(--space-3)' }}>Receipts</h3>
              {r.map((x) => (
                <div key={x.receipt} className="item"><div><div className="item__title">{x.receipt} <Pill>{x.kind}</Pill></div><div className="item__sub">{nameOf(x.by)} · {x.when} · removed {x.removed}</div><code>{x.sha256}</code></div></div>
              ))}
            </div>
          ))}
        </Async>
      </section>

      <Sheet open={forgetting !== null} title="Remove this entry for good?" onClose={() => setForgetting(null)}>
        <p>Its medicine, dose, quoted line, links and acknowledgements are deleted from the graph and cannot be brought back. A receipt with a hash of what was removed stays.</p>
        <label className="field">Reason (optional)<input type="text" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. entered by mistake" /></label>
        <button type="button" className="button button--danger" onClick={() => void doForget()}>Remove for good</button>
      </Sheet>
      <Sheet open={erase} title={`Remove everything about ${title(app.session.person)}?`} onClose={() => setErase(false)}>
        <p>Every entry, dose record and reminder about this person is deleted. Type their name to confirm.</p>
        <label className="field">Type “{app.session.person}”<input type="text" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" /></label>
        <button type="button" className="button button--danger" disabled={typed.trim().toLowerCase() !== app.session.person.toLowerCase()} onClick={() => void doErase()}>Remove everything</button>
      </Sheet>
    </div>
  );
}
