import { Globe2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useToast } from './Toast';
import { tr } from '../lib/i18n';
import { useApp, useLoad } from '../state';

const FALLBACK = ['Asia/Kolkata', 'Asia/Dubai', 'Asia/Singapore', 'Europe/London', 'Europe/Berlin', 'America/New_York', 'America/Chicago', 'America/Los_Angeles', 'Australia/Sydney', 'UTC'];

/** The zones this browser knows by name, with the usual few first; older browsers fall back to a short list. */
export function zoneNames(): string[] {
  const all = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf?.('timeZone') ?? [];
  return [...new Set([...FALLBACK, ...all])];
}

/** The time zone of the person being looked after. It decides which day each dose slot belongs to and when the reminders for it are due, for everyone in
 *  the circle. It is NOT taken from whoever opens the app: a carer abroad sets it once, here. (Quiet hours are different: each carer's own device time.) */
export function CircleTimeZone(): React.JSX.Element {
  const app = useApp();
  const toast = useToast();
  const tz = useLoad((a) => a.api.timezone(), [app.session.circle]);
  const [pick, setPick] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (tz.data) setPick(tz.data.tz); }, [tz.data]);
  const here = Intl.DateTimeFormat().resolvedOptions().timeZone;

  async function save(zone: string): Promise<void> {
    setBusy(true);
    try {
      const r = await app.api.setTimezone(zone);
      toast(`${tr('Time zone saved')}: ${r.tz}`);
      app.bump();
    } catch (e) { toast(e instanceof Error ? e.message : 'Could not save'); } finally { setBusy(false); }
  }

  return (
    <section className="card" aria-labelledby="tz-title" data-testid="circle-timezone">
      <div className="card-head"><h2 id="tz-title">{tr('Time zone of the person you look after')}</h2><Globe2 size={20} aria-hidden="true" /></div>
      <p className="muted small">{tr('It decides which day each dose slot belongs to and when reminders for it are due, for everyone in the circle. Set it to where the person lives, not where you are.')}</p>
      <div className="row row--wrap">
        <label className="field">{tr('Time zone')}
          <select value={pick} onChange={(e) => setPick(e.target.value)} data-testid="tz-select">
            {zoneNames().map((z) => <option key={z} value={z}>{z}</option>)}
          </select>
        </label>
        <button type="button" className="btn" disabled={busy || !pick || pick === tz.data?.tz} onClick={() => void save(pick)} data-testid="tz-save">{tr('Save')}</button>
      </div>
      <p className="muted small">
        {tz.data?.set ? `${tr('Now')}: ${tz.data.tz}.` : `${tr('Not set yet: India time (Asia/Kolkata) is used.')}`} {tr('This device is in')} {here}.
      </p>
    </section>
  );
}
