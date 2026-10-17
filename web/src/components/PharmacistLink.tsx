import { Link2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { Review, ShareLink, ShareRow } from '../api/types';
import { whenLocal } from '../lib/format';
import { useT } from '../lib/i18n';
import { useApp } from '../state';
import { useToast } from './Toast';

/** A read-only link for a pharmacist. The owner makes it, picks how long it lasts, sees how often it was opened and can close it. The link is shown once. */
export function PharmacistLink({ circle, person }: { circle: string; person: string }): React.JSX.Element | null {
  const app = useApp();
  const acct = app.acct;
  const t = useT();
  const toast = useToast();
  const [rows, setRows] = useState<ShareRow[]>([]);
  const [fresh, setFresh] = useState<ShareLink | null>(null);
  const [hours, setHours] = useState(48);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [rev, setRev] = useState(0);

  useEffect(() => {
    if (!acct) return;
    void acct.shares(circle).then(setRows, () => setRows([]));
    if (app.session.circle === circle) void app.api.reviews().then(setReviews, () => setReviews([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [circle, rev]);
  if (!acct) return null;

  async function make(): Promise<void> {
    try { setFresh(await acct!.shareNew(circle, person, hours, '')); setRev((n) => n + 1); } catch (e) { toast(e instanceof Error ? e.message : 'Could not make the link'); }
  }
  async function close(id: string): Promise<void> {
    try { await acct!.shareRevoke(circle, id); setFresh(null); setRev((n) => n + 1); } catch (e) { toast(e instanceof Error ? e.message : 'Could not close it'); }
  }
  const url = fresh ? `${window.location.origin}${fresh.path}` : '';

  return (
    <details className="inspect" data-testid="pharmacist-link">
      <summary><Link2 size={16} aria-hidden="true" /> {t('Share a read-only view with a pharmacist')}</summary>
      <p className="muted small">{t('The link shows the medicines, doses and cross-checks, with no carers names, chat or notes. Anyone who has it can read it until it expires or you close it. They can leave a name and a note.')}</p>
      <div className="row row--wrap">
        <label className="field">{t('Open for')}
          <select value={hours} onChange={(e) => setHours(Number(e.target.value))} data-testid="share-hours">
            <option value={1}>{t('1 hour')}</option><option value={24}>{t('1 day')}</option><option value={48}>{t('2 days')}</option><option value={168}>{t('7 days')}</option>
          </select>
        </label>
        <button type="button" className="btn btn--soft btn--sm" onClick={() => void make()} data-testid="share-make">{t('Make a link')}</button>
      </div>
      {fresh && (
        <div className="banner" data-testid="share-url">
          <input type="text" readOnly value={url} aria-label={t('The link')} onFocus={(e) => e.currentTarget.select()} style={{ width: '100%' }} />
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => void navigator.clipboard?.writeText(url)}>{t('Copy')}</button>
          <span className="muted small"> {t('Shown once. Closes')} {whenLocal(fresh.expires_at)}.</span>
        </div>
      )}
      {rows.length > 0 && (
        <ul className="plain" data-testid="share-rows">
          {rows.map((r) => (
            <li key={r.id}>{r.active ? t('Open until') : r.revoked ? t('Closed') : t('Expired')} {whenLocal(r.expires_at)} · {r.views} {t('views')}
              {r.active && <button type="button" className="btn btn--ghost btn--sm" onClick={() => void close(r.id)}>{t('Close it')}</button>}</li>
          ))}
        </ul>
      )}
      {reviews.length > 0 && (
        <div data-testid="share-reviews">
          <p className="eyebrow">{t('Notes written back')}</p>
          <ul className="plain">{reviews.map((r) => <li key={r.id}>“{r.note || '—'}” — {r.name} ({t('name typed, not verified')}), {whenLocal(r.at)}</li>)}</ul>
        </div>
      )}
    </details>
  );
}
