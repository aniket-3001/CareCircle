import type { ReactNode } from 'react';
import { useT } from '../lib/i18n';

/** A screen's heading: a small crumb, the title, an optional sentence (the pattern every Vayu Project screen uses). */
export function PageHead({ crumb, title, lede, action }: { crumb: string; title: string; lede?: ReactNode; action?: ReactNode }): React.JSX.Element {
  const t = useT();
  return (
    <header>
      <p className="crumb">{t(crumb)}</p>
      <div className="row row--between row--wrap">
        <h1>{t(title)}</h1>
        {action}
      </div>
      {lede && <p className="lede">{typeof lede === 'string' ? t(lede) : lede}</p>}
    </header>
  );
}
