import { BellRing, Check, Clock } from 'lucide-react';
import { motion } from 'motion/react';
import { useState } from 'react';
import { Followups } from '../components/Followups';
import { Handover } from '../components/Handover';
import { Consent } from '../components/Consent';
import { Outcomes } from '../components/Outcomes';
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
import { groupUnseen } from '../lib/packs';

const behind = (score: number, n: number): SeverityKey => (n === 0 ? 'none' : score < 0.2 ? 'minor' : score < 0.5 ? 'moderate' : 'major');

export function CircleScreen(): React.JSX.Element {
  const app = useApp();
  const sole = useLoad((a) => a.api.soleKnowers(), [app.rev]);
  const dep = useLoad((a) => a.api.dependence(), [app.rev]);
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
                <p className="muted">{tr('If they are away, nobody else knows. Ask the others to press "I have seen this".')}</p>
                <ul className="steps">{s.sole.map((x) => <li key={x.dose}><span><b>{title(x.drug)}</b>: only {nameOf(x.only)}</span></li>)}</ul>
                {s.keystone && <p className="muted small">{nameOf(s.keystone)} is the only one who knows {plural(s.keystone_count, 'current entry', 'current entries')}.</p>}
              </section>
            )}
          </Async>
          <Async state={dep}>
            {(d) => d.split_flags.length === 0 ? <></> : (
              <section className="card" aria-labelledby="split-title" data-testid="split-flags">
                <h2 id="split-title">{tr('A flag nobody holds whole')}</h2>
                <p className="muted">{tr('Each carer below knows one of the two medicines, but no carer knows both. Until one of them has seen both entries, nobody has the whole picture of this flag.')}</p>
                <ul className="steps">{d.split_flags.slice(0, 5).map((x) => (
                  <li key={x.drugs.join('+')}><span><b>{title(x.drugs[0])} + {title(x.drugs[1])}</b> ({x.level.toLowerCase()}): {x.knows_first.map(nameOf).join(', ')} {tr('knows')} {title(x.drugs[0])}, {x.knows_second.map(nameOf).join(', ')} {tr('knows')} {title(x.drugs[1])}</span></li>
                ))}</ul>
                {d.keystone && <p className="muted small">{nameOf(d.keystone)} {tr('is the carer whose absence would leave the record least shared')} ({tr('weighted by how connected each lone entry is')}: {d.carers[d.keystone]?.score}).</p>}
              </section>
            )}
          </Async>
          <Async state={div}>
            {(d) => (
              <div className="people-grid">
                {Object.entries(d.carers).map(([c, v], i) => {
                  const packs = groupUnseen(v.unacknowledged);                    // one strip of two ingredients is one change, not two
                  const k = behind(v.divergence, packs.length);
                  const lv = SEVERITY[k];
                  return (
                    <motion.section key={c} className="person" style={{ ['--chip' as string]: lv.solid }} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.08 }} aria-label={`${nameOf(c)}: ${plural(packs.length, 'unseen change')}`}>
                      <div className="person-top">
                        <div>
                          <h3>{nameOf(c)}{c === app.me ? ' (you)' : ''}</h3>
                          <div className="person-num">
                            <strong className="tnum">{packs.length}</strong>
                            <span>{packs.length === 1 ? 'change not seen' : 'changes not seen'}</span>
                          </div>
                        </div>
                        <FaceIcon face={lv.face} size={56} />
                      </div>
                      <div className="bar" role="img" aria-label={`Out-of-date score ${pct(v.divergence)}`} style={{ background: 'rgb(255 255 255 / 0.5)' }}>
                        <i style={{ width: pct(v.divergence), background: 'var(--ink)' }} />
                      </div>
                      {packs.length > 0 ? (
                        <div className="person-unseen">
                          {packs.map((u) => (
                            <div key={u.key} className="item" style={{ alignItems: 'center', gap: 12 }}>
                              <div>
                                <div className="item__title">{u.label} {u.action === 'stop' ? 'stopped' : 'changed'}{u.ingredients.length > 1 ? <span className="muted small"> ({u.ingredients.map(title).join(' + ')})</span> : null}</div>
                                <div className="item__sub">{ago(t - u.age_hours * 3_600_000, t)}</div>
                              </div>
                              {c === app.me && <button type="button" className="btn btn--sm" style={{ whiteSpace: 'nowrap', flexShrink: 0 }} onClick={() => void Promise.all(u.ids.map(ack))}>{tr('I have seen this')}</button>}
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
          <Followups />
          <Handover />
          <details className="more" data-testid="circle-more">
            <summary className="more__summary">{tr('More: appointments, other doses, the week in counts, and the person’s say')}</summary>
            <div className="stack">
              <Appointments />
              <Doses />
              <Outcomes />
              <Consent />
            </div>
          </details>
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
                  <p className="muted">{tr('None due. Reminders go out 4 hours after an unseen change, and again at 12.')}</p>
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
  const log = useLoad((a) => a.api.gives(), [app.rev]);
  const watched = useLoad((a) => a.api.watched(), [app.rev]);
  const today = useLoad((a) => a.api.today(a.now()), [app.rev, app.warp]);
  const [showAll, setShowAll] = useState(false);
  const [drug, setDrug] = useState('');
  const [time, setTime] = useState('');
  const [msg, setMsg] = useState<string | null>(null);

  /** The slots the circle confirmed for this medicine today, as the choices (no typing a slot). A medicine with no fixed times is recorded for the current hour in the circle's own time zone. */
  const slotsFor = (d: string) => (today.data?.items ?? []).filter((i) => i.drug === d);
  const hourNow = (): string => {
    const tz = today.data?.tz ?? 'UTC';
    const h = new Intl.DateTimeFormat('en-GB', { timeZone: tz, hour: '2-digit', hour12: false }).format(new Date()).slice(0, 2);
    return `${today.data?.date ?? new Date().toISOString().slice(0, 10)} ${h}:00`;
  };

  async function give(d: string): Promise<void> {
    try {
      const slots = slotsFor(d);
      const pick = slots.find((i) => i.time === time) ?? slots[0];
      const r = pick ? await app.api.giveSlot(pick.dose_id, pick.time) : await app.api.give(d, hourNow());
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
            <label className="field">{tr('Which dose')}
              {(() => {
                const cur = drug || r[0]?.drug || '';
                const slots = slotsFor(cur);
                return slots.length > 0 ? (
                  <select value={time || slots[0].time} onChange={(e) => setTime(e.target.value)} data-testid="dose-time">
                    {slots.map((i) => <option key={i.time} value={i.time}>{i.time}{i.state === 'given' ? ` (${tr('already given')})` : ''}</option>)}
                  </select>
                ) : <span className="muted small" data-testid="dose-asneeded">{tr('No fixed times: recorded for this hour, once.')}</span>;
              })()}
            </label>
            <div className="row row--wrap">
              <button type="button" className="btn" disabled={!r.length} onClick={() => void give(drug || r[0]?.drug || '')}>Record as {nameOf(app.me)}</button>
              <label className="row" style={{ gap: 6 }}>
                <input type="checkbox" checked={(watched.data ?? []).includes(drug || r[0]?.drug || '')} onChange={(e) => void app.api.watch(drug || r[0]?.drug || '', e.target.checked).then(() => app.bump())} />
                <span className="muted small">{tr('A second carer confirms each dose of this medicine')}</span>
              </label>
            </div>
          </div>
        )}
      </Async>
      {msg && <div className="banner banner--bad" role="alert" data-testid="duplicate">{msg}</div>}
      <Async state={log}>
        {(l) => (l.length ? <><div className="rows">{l.slice(0, showAll ? undefined : 10).map((g) => <div key={g.drug + g.slot} className="item"><div><div className="item__title">{title(g.drug)} <span className="muted">{g.slot}</span></div><div className="item__sub">recorded by {nameOf(g.by)}{g.witness ? `, seen by ${nameOf(g.witness)}` : ''}</div></div>{g.needs_second_carer && (g.by === app.me ? <Pill tone="warn">waiting for a second carer</Pill> : <button type="button" className="btn btn--sm" onClick={() => void app.api.witness(g.drug, g.slot).then(() => { toast('Confirmed'); app.bump(); }, (e) => toast(e.message))}>{tr('I saw it given')}</button>)}</div>)}</div>{l.length > 10 && <button type="button" className="btn btn--ghost btn--sm" onClick={() => setShowAll((v) => !v)}>{showAll ? 'Show fewer' : `Show all ${l.length}`}</button>}</> : <p className="muted">{tr('Nothing recorded yet.')}</p>)}
      </Async>
    </section>
  );
}
