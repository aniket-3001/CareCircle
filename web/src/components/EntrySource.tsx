import { useState } from 'react';
import type { EntrySource as Src } from '../api/types';
import { tr } from '../lib/i18n';
import { useApp } from '../state';

/** What an entry was read from: the text the server read from the photo, voice note or document, with the quoted line marked. Loaded when asked for. */
export function EntrySource({ dose }: { dose: string }): React.JSX.Element {
  const app = useApp();
  const [src, setSrc] = useState<Src | 'error' | null>(null);
  const [open, setOpen] = useState(false);

  function toggle(): void {
    const next = !open;
    setOpen(next);
    if (next && src === null) app.api.entrySource(dose).then(setSrc, () => setSrc('error'));
  }

  const shown = (s: Src): React.ReactNode => {
    const i = s.quote ? s.text.indexOf(s.quote) : -1;
    if (i < 0) return s.text;
    return <>{s.text.slice(0, i)}<mark>{s.quote}</mark>{s.text.slice(i + s.quote.length)}</>;
  };

  return (
    <div>
      <button type="button" className="btn btn--ghost btn--sm" style={{ paddingInline: 0 }} onClick={toggle} aria-expanded={open} data-testid="show-source">
        {open ? tr('Hide what it was read from') : tr('Show what it was read from')}
      </button>
      {open && (
        <div className="item__sub" data-testid="source-text">
          {src === null && tr('Loading…')}
          {src === 'error' && tr('Could not load it.')}
          {src && src !== 'error' && (
            <>
              {src.has_source ? <pre className="quote" style={{ whiteSpace: 'pre-wrap' }}>{shown(src)}</pre> : null}
              {src.file_sha256 && <span className="muted small" data-testid="file-fingerprint">{tr('Fingerprint of the file that was read')}: {src.file_sha256.slice(0, 12)}… ({Math.max(1, Math.round(src.file_bytes / 1024))} KB). </span>}
              <span className="muted small">{src.has_source ? tr('This is the text the server read, kept so the quoted line can be checked. The picture or recording itself is not stored.') : tr('Typed in by hand, so there is no photo, voice note or document behind it.')}</span>
            </>
          )}
        </div>
      )}
    </div>
  );
}
