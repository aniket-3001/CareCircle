import { Fingerprint as Icon } from 'lucide-react';
import { useState } from 'react';
import { Async } from './Async';
import { useT } from '../lib/i18n';
import { useApp, useLoad } from '../state';

/** A fingerprint of the history: keep the line it shows (or print it), and later check that the first entries are exactly as they were. It shows an entry
 *  was changed or removed after the fact; it does not show an entry is right. */
export function Fingerprint(): React.JSX.Element {
  const app = useApp();
  const t = useT();
  const d = useLoad((a) => a.api.digest(), [app.rev]);
  const [saved, setSaved] = useState('');
  const [verdict, setVerdict] = useState<'same' | 'different' | 'bad' | null>(null);

  async function check(): Promise<void> {
    const m = /^\s*(\d{1,6}):([0-9a-f]{64})\s*$/i.exec(saved);
    if (!m) { setVerdict('bad'); return; }
    const r = await app.api.digest(Number(m[1]));
    setVerdict(r.entries === Number(m[1]) && r.head === m[2].toLowerCase() ? 'same' : 'different');
  }

  return (
    <details className="inspect" data-testid="fingerprint">
      <summary><Icon size={16} aria-hidden="true" /> {t('History fingerprint')}</summary>
      <Async state={d}>
        {(r) => (
          <>
            <p className="muted small">{t('Keep this line somewhere safe. Later, paste it below to check that these entries are exactly as they were. It shows an entry was changed or removed after the fact; it does not show an entry is right.')}</p>
            <code className="tnum" data-testid="fingerprint-line" style={{ wordBreak: 'break-all' }}>{r.entries > 0 ? `${r.entries}:${r.head}` : t('No entries yet.')}</code>
            <div className="row">
              <input type="text" value={saved} onChange={(e) => { setSaved(e.target.value); setVerdict(null); }} aria-label={t('A line you kept earlier')} placeholder="12:ab34…" data-testid="fingerprint-input" />
              <button type="button" className="btn btn--soft btn--sm" onClick={() => void check()} disabled={!saved.trim()} data-testid="fingerprint-check">{t('Check')}</button>
            </div>
            {verdict && <p role="status" data-testid="fingerprint-verdict">{verdict === 'same' ? t('Those entries are exactly as they were.') : verdict === 'different' ? t('Those entries are NOT the same as when the line was kept: one was changed or removed.') : t('That does not look like a kept line (a number, a colon and 64 letters or digits).')}</p>}
          </>
        )}
      </Async>
    </details>
  );
}
