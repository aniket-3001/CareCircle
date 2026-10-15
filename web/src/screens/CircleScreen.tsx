import { useState } from 'react';
import { Async } from '../components/Async';
import { Pill } from '../components/Pill';
import { Segmented } from '../components/Segmented';
import { useToast } from '../components/Toast';
import { ago, nameOf, pct, plural, title, when } from '../lib/format';
import { useApp, useLoad } from '../state';

export function CircleScreen(): React.JSX.Element {
  const app = useApp();
  const toast = useToast();
  const t = app.now();
  const div = useLoad((a) => a.api.divergence(a.now()), [app.warp]);
  const nudges = useLoad((a) => a.api.nudges(a.now()), [app.warp]);

  async function ack(dose: string): Promise<void> {
    try {
      await app.api.ack(dose);
      toast('Acknowledged');
      app.bump();
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not acknowledge');
    }
  }

  return (
    <div className="screen">
      <h1 className="headline">Who has seen what</h1>
      <Async state={div}>
        {(d) => (
          <section className="card" aria-labelledby="div-title">
            <h2 className="card__title" id="div-title">Carers and their unseen changes</h2>
            <p className="muted">
              {d.most_out_of_date ? `${nameOf(d.most_out_of_date)} is furthest behind.` : 'Everyone has seen every change.'} Older unseen changes count more (half-life {d.half_life_hours} h; the weights are assumptions).
            </p>
            <div className="rows">
              {Object.entries(d.carers).map(([c, v]) => (
                <div key={c} className="stack" style={{ padding: 'var(--space-3) 0' }}>
                  <div className="row row--between">
                    <b>{nameOf(c)}{c === app.session.as ? ' (you)' : ''}</b>
                    {v.unacknowledged.length ? <Pill tone="warn">{plural(v.unacknowledged.length, 'change')} not seen</Pill> : <Pill tone="ok">up to date</Pill>}
                  </div>
                  <div className="bar" role="img" aria-label={`Out-of-date score ${pct(v.divergence)}`}>
                    <i style={{ width: pct(v.divergence), background: v.divergence > 0.5 ? 'var(--bad)' : 'var(--c-drug)' }} />
                  </div>
                  {v.unacknowledged.map((u) => (
                    <div key={u.dose} className="item">
                      <div>
                        <div className="item__title">{title(u.drug)} {u.action === 'stop' ? 'stopped' : 'changed'}</div>
                        <div className="item__sub">{ago(t - u.age_hours * 3_600_000, t)}</div>
                      </div>
                      {c === app.session.as && <button type="button" className="button button--small" onClick={() => void ack(u.dose)}>I have seen this</button>}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </section>
        )}
      </Async>

      <section className="card" aria-labelledby="warp-title">
        <h2 className="card__title" id="warp-title">Time warp</h2>
        <p className="muted">Pretend it is later, to see reminders appear without waiting. Showing {app.warp === 0 ? 'now' : `now + ${app.warp} hours (${when(t)})`}.</p>
        <Segmented name="warp" label="Hours to add to now" value={app.warp} onChange={app.setWarp}
          options={[{ value: 0, label: 'Now' }, { value: 6, label: '+6 h' }, { value: 13, label: '+13 h' }, { value: 24, label: '+1 day' }]} />
      </section>

      <Async state={nudges}>
        {(n) => (
          <section className="card" aria-labelledby="nudge-title">
            <h2 className="card__title" id="nudge-title">Reminders due</h2>
            {n.length === 0 ? <p className="muted">None due. A reminder is produced once an unseen change is 4 hours old (and an escalation at 12 hours).</p> : (
              <div className="rows">
                {n.map((x) => (
                  <div key={`${x.kind}${x.notify}${x.drug}`} className="item">
                    <div>
                      <div className="item__title">{x.message.text}</div>
                      <div className="item__sub">to {nameOf(x.notify)} · {x.kind === 'escalate' ? 'escalation' : 'reminder'} · produced once</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}
      </Async>

      <Doses />
    </div>
  );
}

function Doses(): React.JSX.Element {
  const app = useApp();
  const toast = useToast();
  const reg = useLoad((a) => a.api.regimen());
  const log = useLoad((a) => a.api.gives());
  const [drug, setDrug] = useState('');
  const [slot, setSlot] = useState(`${new Date().toISOString().slice(0, 10)} 08:00`);
  const [msg, setMsg] = useState<string | null>(null);

  async function give(d: string): Promise<void> {
    try {
      const r = await app.api.give(d, slot);
      if (r.given) { setMsg(null); toast('Recorded'); app.bump(); } else setMsg(`Already recorded by ${nameOf(r.already_given_by ?? '')}. ${r.note ?? ''}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not record');
    }
  }

  return (
    <section className="card" aria-labelledby="dose-title">
      <h2 className="card__title" id="dose-title">Doses given</h2>
      <p className="muted">A dose slot can be recorded once. If two carers try, the second is told who already did.</p>
      <Async state={reg}>
        {(r) => (
          <div className="grid-2">
            <label className="field">Medicine
              <select value={drug || r[0]?.drug || ''} onChange={(e) => setDrug(e.target.value)}>{r.map((x) => <option key={x.id} value={x.drug}>{title(x.drug)}</option>)}</select>
            </label>
            <label className="field">Slot
              <input type="text" value={slot} onChange={(e) => setSlot(e.target.value)} />
            </label>
            <div className="row">
              <button type="button" className="button" disabled={!r.length} onClick={() => void give(drug || r[0]?.drug || '')}>Record as {nameOf(app.session.as)}</button>
            </div>
          </div>
        )}
      </Async>
      {msg && <div className="flag flag--major" role="alert" data-testid="duplicate">{msg}</div>}
      <Async state={log}>
        {(l) => (l.length ? <div className="rows">{l.map((g) => <div key={g.drug + g.slot} className="item"><div><div className="item__title">{title(g.drug)} <span className="muted">{g.slot}</span></div><div className="item__sub">recorded by {nameOf(g.by)}</div></div></div>)}</div> : <p className="muted">Nothing recorded yet.</p>)}
      </Async>
    </section>
  );
}
