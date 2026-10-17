import { Fingerprint as Icon } from 'lucide-react';
import { useState } from 'react';
import type { ChainCheck } from '../api/types';
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
  const [chain, setChain] = useState<ChainCheck | null>(null);

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
            <div className="row">
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => void app.api.chain().then(setChain)} data-testid="chain-check">{t('Check the stored log')}</button>
            </div>
            {chain && (
              <p role="status" data-testid="chain-verdict">
                {chain.ok
                  ? `${t('The log is unbroken')}: ${chain.events} ${t('events')}, ${chain.entries_logged} ${t('entries, each still as it was written')}.${chain.entries_not_logged > 0 ? ` ${chain.entries_not_logged} ${t('older entries are from before the log began')}.` : ''}${chain.entries_adopted > 0 ? ` ${chain.entries_adopted} ${t('older entries were added to the log later, so they are covered only from then on')}.` : ''}`
                  : `${t('The log is NOT intact')}: ${chain.first_problem?.why ?? ''} (${t('event')} ${chain.first_problem?.seq ?? ''}).`}
              </p>
            )}
            {chain?.ok && chain.entries_not_logged > 0 && (
              <div className="row">
                <button type="button" className="btn btn--ghost btn--sm" onClick={() => void app.api.adoptChain().then(() => app.api.chain().then(setChain))} data-testid="chain-adopt">{t('Add the older entries to the log')}</button>
              </div>
            )}
            {verdict && <p role="status" data-testid="fingerprint-verdict">{verdict === 'same' ? t('Those entries are exactly as they were.') : verdict === 'different' ? t('Those entries are NOT the same as when the line was kept: one was changed or removed.') : t('That does not look like a kept line (a number, a colon and 64 letters or digits).')}</p>}
          </>
        )}
      </Async>
    </details>
  );
}
