import { BellRing, Check, Clock } from 'lucide-react';
import { motion } from 'motion/react';
import { useState } from 'react';
import { Appointments } from '../components/Appointments';
import { Async } from '../components/Async';
import { FaceIcon } from '../components/Face';
import { PageHead } from '../components/PageHead';
import { Pill } from '../components/Pill';
import { Segmented } from '../components/Segmented';
import { useToast } from '../components/Toast';
import { SEVERITY, type SeverityKey } from '../design/levels';
import { ago, nameOf, pct, plural, title, when } from '../lib/format';
import { useApp, useLoad } from '../state';
import { tr } from '../lib/i18n';

const behind = (score: number, n: number): SeverityKey => (n === 0 ? 'none' : score < 0.2 ? 'minor' : score < 0.5 ? 'moderate' : 'major');

export function CircleScreen(): React.JSX.Element {
  const app = useApp();
  const sole = useLoad((a) => a.api.soleKnowers(), [app.rev]);
  const toast = useToast();
  const t = app.now();
  const div = useLoad((a) => a.api.divergence(a.now()), [app.warp]);
  const nudges = useLoad((a) => a.api.reminders(a.now()), [app.warp]);

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
      <PageHead crumb={tr('The circle')} title={tr('Who has seen what')} lede={tr('Every change is shown to every carer. Until someone acknowledges it, they count as behind, and older unseen changes count more.')} />
      <div className="layout">
        <div className="col">
          <Async state={sole}>
            {(s) => s.sole.length === 0 ? <></> : (
              <section className="card" aria-labelledby="sole-title" data-testid="sole-knowers">
                <h2 id="sole-title">{tr('Only one carer knows')}</h2>
                <p className="muted">{tr('If that carer is away, nobody else has been told. Ask the others to open the change and press "I have seen this".')}</p>
                <ul className="steps">{s.sole.map((x) => <li key={x.dose}><span><b>{title(x.drug)}</b>: only {nameOf(x.only)}</span></li>)}</ul>
                {s.keystone && <p className="muted small">{nameOf(s.keystone)} is the only one who knows {plural(s.keystone_count, 'current entry', 'current entries')}.</p>}
              </section>
            )}
          </Async>
          <Async state={div}>
            {(d) => (
              <div className="people-grid">
                {Object.entries(d.carers).map(([c, v], i) => {
                  const k = behind(v.divergence, v.unacknowledged.length);
                  const lv = SEVERITY[k];
                  return (
                    <motion.section key={c} className="person" style={{ ['--chip' as string]: lv.solid }} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.08 }} aria-label={`${nameOf(c)}: ${plural(v.unacknowledged.length, 'unseen change')}`}>
                      <div className="person-top">
                        <div>
                          <h3>{nameOf(c)}{c === app.me ? ' (you)' : ''}</h3>
                          <div className="person-num">
                            <strong className="tnum">{v.unacknowledged.length}</strong>
                            <span>{v.unacknowledged.length === 1 ? 'change not seen' : 'changes not seen'}</span>
                          </div>
                        </div>
                        <FaceIcon face={lv.face} size={56} />
                      </div>
                      <div className="bar" role="img" aria-label={`Out-of-date score ${pct(v.divergence)}`} style={{ background: 'rgb(255 255 255 / 0.5)' }}>
                        <i style={{ width: pct(v.divergence), background: 'var(--ink)' }} />
                      </div>
                      {v.unacknowledged.length > 0 ? (
                        <div className="person-unseen">
                          {v.unacknowledged.map((u) => (
                            <div key={u.dose} className="item" style={{ alignItems: 'center', gap: 12 }}>
                              <div>
                                <div className="item__title">{title(u.drug)} {u.action === 'stop' ? 'stopped' : 'changed'}</div>
                                <div className="item__sub">{ago(t - u.age_hours * 3_600_000, t)}</div>
                              </div>
                              {c === app.me && <button type="button" className="btn btn--sm" style={{ whiteSpace: 'nowrap', flexShrink: 0 }} onClick={() => void ack(u.dose)}>{tr('I have seen this')}</button>}
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="row"><Check size={18} aria-hidden="true" /> <span>{tr('Up to date with every change.')}</span></div>
                      )}
                    </motion.section>
                  );
                })}
              </div>
            )}
          </Async>
          <Appointments />
          <Doses />
        </div>
        <div className="col">
          {app.isDemo && (
            <section className="card" aria-labelledby="warp-title">
              <div className="row"><Clock size={20} strokeWidth={1.75} aria-hidden="true" /><h2 id="warp-title">{tr('Time warp (demo only)')}</h2></div>
              <p className="muted">{tr('Pretend it is later, to see reminders appear without waiting.')} {tr('Showing')} {app.warp === 0 ? tr('now') : `now + ${app.warp} h (${when(t)})`}. {tr('Real circles are always read as of now.')}</p>
              <Segmented name="warp" label="Hours to add to now" value={app.warp} onChange={app.setWarp} options={[{ value: 0, label: 'Now' }, { value: 6, label: '+6 h' }, { value: 13, label: '+13 h' }, { value: 24, label: '+1 day' }]} />
            </section>
          )}
          <Async state={nudges}>
            {(n) => (
              <section className="card" aria-labelledby="nudge-title">
                <div className="row"><BellRing size={20} strokeWidth={1.75} aria-hidden="true" /><h2 id="nudge-title">{tr('Reminders due')}</h2></div>
                {n.length === 0 ? (
                  <p className="muted">{tr('None due. A reminder is produced once an unseen change is 4 hours old, and an escalation at 12 hours.')}</p>
                ) : (
                  <div className="rows">
                    {n.map((x) => (
                      <div key={`${x.kind}${x.notify}${x.drug}`} className="item">
                        <div>
                          <div className="item__title">{x.message.text}</div>
                          <div className="item__sub">to {nameOf(x.notify)} · {x.kind === 'escalate' ? 'escalation' : 'reminder'} · {x.delivered ? 'already sent to the chat' : 'sent once, to the linked chat'}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            )}
          </Async>
        </div>
      </div>
    </div>
  );
}

function Doses(): React.JSX.Element {
  const app = useApp();
  const toast = useToast();
  const reg = useLoad((a) => a.api.regimen());
  const log = useLoad((a) => a.api.gives());
  const [showAll, setShowAll] = useState(false);
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
      <div className="card-head">
        <h2 id="dose-title">{tr('Doses given')}</h2>
        <Pill tone="info">once per slot</Pill>
      </div>
      <p className="muted">{tr('A dose slot can be recorded once. If two carers try, the second is told who already did.')}</p>
      <Async state={reg}>
        {(r) => (
          <div className="grid-2">
            <label className="field">{tr('Medicine')}
              <select value={drug || r[0]?.drug || ''} onChange={(e) => setDrug(e.target.value)}>{r.map((x) => <option key={x.id} value={x.drug}>{title(x.drug)}</option>)}</select>
            </label>
            <label className="field">{tr('Slot')}
              <input type="text" value={slot} onChange={(e) => setSlot(e.target.value)} />
            </label>
            <div className="row">
              <button type="button" className="btn" disabled={!r.length} onClick={() => void give(drug || r[0]?.drug || '')}>Record as {nameOf(app.me)}</button>
            </div>
          </div>
        )}
      </Async>
      {msg && <div className="banner banner--bad" role="alert" data-testid="duplicate">{msg}</div>}
      <Async state={log}>
        {(l) => (l.length ? <><div className="rows">{l.slice(0, showAll ? undefined : 10).map((g) => <div key={g.drug + g.slot} className="item"><div><div className="item__title">{title(g.drug)} <span className="muted">{g.slot}</span></div><div className="item__sub">recorded by {nameOf(g.by)}</div></div></div>)}</div>{l.length > 10 && <button type="button" className="btn btn--ghost btn--sm" onClick={() => setShowAll((v) => !v)}>{showAll ? 'Show fewer' : `Show all ${l.length}`}</button>}</> : <p className="muted">{tr('Nothing recorded yet.')}</p>)}
      </Async>
    </section>
  );
}
