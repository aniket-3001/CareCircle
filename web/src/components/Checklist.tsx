import { CalendarClock, Check, Clock } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { StockRow, Suggestion, TodayItem, TodayView } from '../api/types';
import { useT, tr } from '../lib/i18n';
import { nameOf, productName, shown, title } from '../lib/format';
import { useApp, useLoad } from '../state';
import { canonicalZone } from './CircleTimeZone';
import { Pill } from './Pill';
import { Sheet } from './Sheet';
import { useToast } from './Toast';

const STATE: Record<TodayItem['state'], { text: string; tone: 'ok' | 'info' | 'warn' | 'mute' }> = {
  given: { text: 'Given', tone: 'ok' },
  due: { text: 'Due now', tone: 'info' },
  not_marked: { text: 'Not marked as given yet', tone: 'warn' },
  upcoming: { text: 'Later today', tone: 'mute' },
  before: { text: 'Before it was recorded', tone: 'mute' },
};

/** Today's doses, from the times a carer confirmed: one row per slot, with who marked it given. It reports what is recorded ("not marked as given yet");
 *  it never says what to take or skip. A medicine with no confirmed times is listed below with a way to set them. */
export function Checklist(): React.JSX.Element | null {
  const app = useApp();
  const t = useT();
  const toast = useToast();
  const today = useLoad((a) => a.api.today(a.now()), [app.warp]);
  const [setting, setSetting] = useState<TodayView['unscheduled'][number] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  // The circle's time zone decides which day a slot belongs to. It is never taken silently from whoever opens this first: if nobody has set it and this device
  // is somewhere else, we ask (a carer abroad is a common case), and it can be changed in the Account screen.
  const zone = useLoad((a) => a.api.timezone(), [app.session.circle]);
  const here = canonicalZone(Intl.DateTimeFormat().resolvedOptions().timeZone);
  const askZone = !!zone.data && !zone.data.set && !!here && here !== canonicalZone(zone.data.tz);
  async function chooseZone(z: string): Promise<void> {
    try { await app.api.setTimezone(z); app.bump(); } catch (e) { toast(e instanceof Error ? e.message : 'Could not save'); }
  }

  const [clash, setClash] = useState<{ item: TodayItem; note: string; by: string } | null>(null);

  async function give(i: TodayItem, bothPrescribed = false): Promise<void> {
    setBusy(`${i.dose_id}|${i.time}`);
    try {
      const r = await app.api.giveSlot(i.dose_id, i.time, bothPrescribed);
      if (!r.given && r.reason === 'shared_ingredient') {                    // another product with the same ingredient was recorded: say so, and let a carer who knows both were prescribed say it
        setClash({ item: i, note: r.note ?? '', by: r.already_given_by ?? '' });
        return;
      }
      setClash(null);
      toast(r.given ? (r.override ? `${shown(i)} at ${i.time} recorded as a second source.` : `${shown(i)} at ${i.time} marked as given.`) : `Already marked as given by ${nameOf(r.already_given_by ?? '')}. Check with them before giving another.`);
      app.bump();
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not mark it');
    } finally {
      setBusy(null);
    }
  }

  return (
    <Checked today={today.data} error={today.error} onGive={(i) => give(i)} clash={clash} onForce={(i) => give(i, true)} onCancelClash={() => setClash(null)} busy={busy} onSet={setSetting} zone={{ set: zone.data?.set ?? true, circle: zone.data?.tz ?? '', here, ask: askZone, choose: chooseZone }} setting={setting} closeSet={() => setSetting(null)} t={t} />
  );
}

function Checked({ today, error, onGive, clash, onForce, onCancelClash, busy, onSet, zone, setting, closeSet, t }: {
  today: TodayView | undefined; error: string | undefined; onGive: (i: TodayItem) => Promise<void>; busy: string | null;
  clash: { item: TodayItem; note: string; by: string } | null; onForce: (i: TodayItem) => Promise<void>; onCancelClash: () => void;
  onSet: (u: TodayView['unscheduled'][number]) => void;
  zone: { set: boolean; circle: string; here: string; ask: boolean; choose: (z: string) => Promise<void> }; setting: TodayView['unscheduled'][number] | null; closeSet: () => void; t: (s: string) => string;
}): React.JSX.Element | null {
  if (error || !today) return null;
  const nothing = today.items.length === 0 && today.unscheduled.length === 0 && today.as_needed.length === 0;
  if (nothing) return null;
  const late = today.counts.not_marked;
  return (
    <section className="card" aria-labelledby="checklist-title" data-testid="checklist">
      <div className="card-head">
        <h2 id="checklist-title"><CalendarClock size={20} strokeWidth={1.75} aria-hidden="true" /> {t("Today's doses")}</h2>
        <Pill tone={late ? 'warn' : 'info'}>{today.counts.given} / {today.items.length - today.counts.before} {t('marked given')}</Pill>
      </div>
      <p className="muted small" data-testid="checklist-zone">{t('Times are in')} {today.tz}{!zone.set ? ` (${t('not set yet')})` : ''}. {t('Change it in Account.')}</p>
      {zone.ask && (
        <div className="banner banner--stack" role="status" data-testid="tz-prompt">
          <p>{t('This device is in')} <b>{zone.here}</b>, {t('but this circle uses')} <b>{zone.circle}</b>. {t('Which time zone is the person you look after in?')}</p>
          <div className="row row--wrap">
            <button type="button" className="btn btn--sm" onClick={() => void zone.choose(zone.here)} data-testid="tz-use-device">{t('Use')} {zone.here}</button>
            <button type="button" className="btn btn--soft btn--sm" onClick={() => void zone.choose(zone.circle)} data-testid="tz-keep">{t('Keep')} {zone.circle}</button>
          </div>
        </div>
      )}
      {clash && (
        <div className="banner banner--warn banner--stack" role="alert" data-testid="clash">
          <p><b>{shown(clash.item)}</b> {t('was not recorded.')} {clash.note}</p>
          <div className="row row--wrap">
            <button type="button" className="btn btn--sm" onClick={() => void onForce(clash.item)} data-testid="both-prescribed">{t('Both were prescribed: record it anyway')}</button>
            <button type="button" className="btn btn--soft btn--sm" onClick={onCancelClash} data-testid="clash-cancel">{t('Cancel')}</button>
          </div>
          <p className="muted small">{t('Choose this only if both products were really prescribed and both were given. The record will show two doses of the shared ingredient at this time, marked as a second source.')}</p>
        </div>
      )}
      {late > 0 && <p className="muted" role="status" data-testid="checklist-late">{late === 1 ? t('1 dose is not marked as given yet.') : `${late} ${t('doses are not marked as given yet.')}`} {t('Check with the others before marking one.')}</p>}
      <div className="rows">
        {today.items.map((i) => (
          <div key={`${i.dose_id}|${i.time}`} className="item" data-testid="slot" data-state={i.state}>
            <div>
              <div className="item__title"><Clock size={16} aria-hidden="true" /> {i.time} · {shown(i)} <span className="muted">{i.dose_text}</span></div>
              {i.brand && <div className="item__sub muted" data-testid="slot-brand">{t('as')} {productName(i.brand)}</div>}
              {i.ingredients && <div className="item__sub muted" data-testid="slot-ingredients">{t('one tablet of')} {i.ingredients.map(title).join(' + ')}</div>}
              <div className="item__sub">
                <Pill tone={STATE[i.state].tone}>{t(STATE[i.state].text)}</Pill>
                {i.given_by && <> {t('by')} {nameOf(i.given_by)}</>}
                {i.needs_second_carer && <> · {t('a second carer should confirm')}</>}
              </div>
            </div>
            {i.state !== 'given' && (
              <button type="button" className="btn btn--sm" disabled={busy === `${i.dose_id}|${i.time}`} onClick={() => void onGive(i)} data-testid="give-slot">
                <Check size={16} aria-hidden="true" /> {t('Mark as given')}
              </button>
            )}
          </div>
        ))}
      </div>
      {today.unscheduled.length > 0 && (
        <div className="rows" data-testid="unscheduled">
          <p className="eyebrow">{t('No times set yet')}</p>
          {today.unscheduled.map((u) => (
            <div key={u.dose_id} className="item">
              <div>
                <div className="item__title">{shown(u)} <span className="muted">{u.dose_text} {u.freq_text}</span></div>
                <div className="item__sub">{u.suggestion.understood ? t('The label says') + ` ${u.suggestion.label}.` : u.suggestion.why}</div>
              </div>
              <button type="button" className="btn btn--soft btn--sm" onClick={() => onSet(u)} data-testid="set-times">{t('Set times')}</button>
            </div>
          ))}
        </div>
      )}
      {today.as_needed.length > 0 && <p className="muted small">{t('Taken as needed, so no fixed times:')} {today.as_needed.map((a) => shown(a)).join(', ')}.</p>}
      <Packs today={today} />
      <p className="muted small">{today.tz} · {today.date}</p>
      <SetTimes u={setting} close={closeSet} />
    </section>
  );
}

/** How many doses are left in each pack, counted by a person. Doses marked given after the count come off it; the days are 'about', from what is on the record. */
function Packs({ today }: { today: TodayView }): React.JSX.Element | null {
  const app = useApp();
  const t = useT();
  const toast = useToast();
  const stock = useLoad((a) => a.api.stock(a.now()), [app.warp]);
  const [vals, setVals] = useState<Record<string, string>>({});
  const meds = [...new Map(today.items.map((i) => [i.dose_id, i.drug] as const)).entries()];
  if (meds.length === 0) return null;
  const by: Record<string, StockRow> = Object.fromEntries((stock.data ?? []).map((s) => [s.dose_id, s]));

  async function save(id: string, drug: string): Promise<void> {
    const n = Number(vals[id]);
    if (!Number.isInteger(n) || n < 0 || n > 9999) { toast(t('Enter a whole number from 0 to 9999.')); return; }
    try {
      await app.api.setStock(id, n);
      toast(`${title(drug)}: ${n} ${t('doses left saved.')}`);
      setVals((v) => ({ ...v, [id]: '' }));
      app.bump();
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not save');
    }
  }

  return (
    <details className="inspect" data-testid="packs">
      <summary>{t('Packs: how many doses are left')}</summary>
      <div className="rows">
        {meds.map(([id, drug]) => {
          const s = by[id];
          return (
            <div key={id} className="item" data-testid="pack">
              <div>
                <div className="item__title">{title(drug)}</div>
                <div className="item__sub" data-testid="pack-left">
                  {s ? `${s.doses_left} ${t('doses left on the record')}${s.days_left !== null ? ` · ${t('about')} ${s.days_left} ${s.days_left === 1 ? t('day') : t('days')}` : ''}` : t('Not counted yet')}
                </div>
              </div>
              <div className="row">
                <input type="number" inputMode="numeric" min={0} max={9999} aria-label={`${title(drug)}: ${t('doses left in the pack')}`} value={vals[id] ?? ''}
                  onChange={(e) => setVals((v) => ({ ...v, [id]: e.target.value }))} style={{ width: '5.5rem' }} data-testid="pack-input" />
                <button type="button" className="btn btn--soft btn--sm" onClick={() => void save(id, drug)} data-testid="pack-save">{t('Save count')}</button>
              </div>
            </div>
          );
        })}
      </div>
      <p className="muted small">{t('Count the doses in the pack and enter the number. Doses marked as given after that come off it. A pack can also be used another way, so check the pack itself.')}</p>
    </details>
  );
}

function SetTimes({ u, close }: { u: TodayView['unscheduled'][number] | null; close: () => void }): React.JSX.Element {
  const app = useApp();
  const toast = useToast();
  const [times, setTimes] = useState<string[]>([]);
  const [asNeeded, setAsNeeded] = useState(false);
  const [ends, setEnds] = useState('');
  const [busy, setBusy] = useState(false);
  const s: Suggestion | undefined = u?.suggestion;
  useEffect(() => {
    if (!u) return;
    setTimes(u.suggestion.times);
    setAsNeeded(u.suggestion.as_needed);
    setEnds('');
  }, [u]);

  async function save(): Promise<void> {
    if (!u) return;
    setBusy(true);
    try {
      await app.api.setSchedule(u.dose_id, asNeeded ? [] : times, asNeeded, ends);
      toast(`${shown(u)}: times saved.`);
      close();
      app.bump();
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not save');
    } finally {
      setBusy(false);
    }
  }

  const setAt = (i: number, v: string): void => setTimes((cur) => cur.map((x, j) => (j === i ? v : x)));
  return (
    <Sheet open={u !== null} title={u ? `${tr('Times for')} ${shown(u)}` : ''} onClose={close}>
      {u && (
        <>
          <p className="muted">{s?.understood && !s.as_needed ? `${tr('The label says')} ${s.label}. ${tr('These times are only a starting point: set the ones on the pack.')}` : s?.why}</p>
          <label className="row"><input type="checkbox" checked={asNeeded} onChange={(e) => setAsNeeded(e.target.checked)} data-testid="as-needed" /> {tr('Taken only when needed (no fixed times)')}</label>
          {!asNeeded && (
            <div className="stack">
              {times.map((x, i) => (
                <div key={i} className="row">
                  <input type="time" value={x} aria-label={`${tr('Time')} ${i + 1}`} onChange={(e) => setAt(i, e.target.value)} data-testid="time-input" />
                  <button type="button" className="btn btn--ghost btn--sm" onClick={() => setTimes((cur) => cur.filter((_, j) => j !== i))}>{tr('Remove')}</button>
                </div>
              ))}
              {times.length < 6 && <button type="button" className="btn btn--soft btn--sm" onClick={() => setTimes((cur) => [...cur, '12:00'])}>{tr('Add a time')}</button>}
            </div>
          )}
          <label className="field">{tr('Last day of the course (optional)')}<input type="date" value={ends} onChange={(e) => setEnds(e.target.value)} data-testid="ends-on" /></label>
          <button type="button" className="btn" disabled={busy || (!asNeeded && times.length === 0)} onClick={() => void save()} data-testid="save-times">{tr('Save times')}</button>
        </>
      )}
    </Sheet>
  );
}
