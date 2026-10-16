import { MoonStar } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useToast } from './Toast';
import { tr } from '../lib/i18n';
import { useApp } from '../state';

const hours = Array.from({ length: 24 }, (_, h) => h);
const label = (h: number): string => `${String(h).padStart(2, '0')}:00`;

/** Hours when reminders are held back. A reminder due in that window is not lost: it goes out when the window ends. */
export function QuietHours(): React.JSX.Element {
  const app = useApp();
  const toast = useToast();
  const [from, setFrom] = useState<number | ''>('');
  const [to, setTo] = useState<number | ''>('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    void app.acct!.quiet().then((q) => { setFrom(q.from ?? ''); setTo(q.to ?? ''); }, () => undefined);
  }, [app.acct]);

  async function save(off: boolean): Promise<void> {
    setBusy(true);
    try {
      const tz = -new Date().getTimezoneOffset();                               // minutes ahead of UTC, as this browser reports it
      const q = await app.acct!.setQuiet(off || from === '' || to === '' ? null : from, off || from === '' || to === '' ? null : to, tz);
      setFrom(q.from ?? ''); setTo(q.to ?? '');
      toast(q.from === null ? 'Quiet hours are off.' : 'Quiet hours saved.');
    } catch (e) { toast(e instanceof Error ? e.message : 'Could not save'); } finally { setBusy(false); }
  }
  return (
    <section className="card" aria-labelledby="quiet-title" data-testid="quiet-hours">
      <div className="card-head"><h2 id="quiet-title">{tr('Quiet hours')}</h2><MoonStar size={20} aria-hidden="true" /></div>
      <p className="muted small">{tr('No reminders in these hours, in your local time. A reminder due then is held and sent when they end.')}</p>
      <div className="row row--wrap">
        <label className="field">{tr('From')}
          <select value={from} onChange={(e) => setFrom(e.target.value === '' ? '' : Number(e.target.value))}><option value="">{tr('Off')}</option>{hours.map((h) => <option key={h} value={h}>{label(h)}</option>)}</select>
        </label>
        <label className="field">{tr('Until')}
          <select value={to} onChange={(e) => setTo(e.target.value === '' ? '' : Number(e.target.value))}><option value="">{tr('Off')}</option>{hours.map((h) => <option key={h} value={h}>{label(h)}</option>)}</select>
        </label>
      </div>
      <div className="row">
        <button type="button" className="btn btn--soft btn--sm" disabled={busy || from === '' || to === ''} onClick={() => void save(false)}>{tr('Save')}</button>
        <button type="button" className="btn btn--ghost btn--sm" disabled={busy || (from === '' && to === '')} onClick={() => void save(true)}>{tr('Turn off')}</button>
      </div>
    </section>
  );
}
