import type { ReactNode } from 'react';

/** A screen's heading: a small crumb, the title, an optional sentence (the pattern every Vayu Project screen uses). */
export function PageHead({ crumb, title, lede, action }: { crumb: string; title: string; lede?: ReactNode; action?: ReactNode }): React.JSX.Element {
  return (
    <header>
      <p className="crumb">{crumb}</p>
      <div className="row row--between row--wrap">
        <h1>{title}</h1>
        {action}
      </div>
      {lede && <p className="lede">{lede}</p>}
    </header>
  );
}
