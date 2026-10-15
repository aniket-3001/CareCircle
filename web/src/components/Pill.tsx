import type { ReactNode } from 'react';

export type Tone = 'ok' | 'warn' | 'bad' | 'info' | 'mute';

export const Pill = ({ tone = 'mute', children }: { tone?: Tone; children: ReactNode }): React.JSX.Element => (
  <span className={`pill pill--${tone}`}>{children}</span>
);

export const Skeleton = (): React.JSX.Element => (
  <div className="skeleton" aria-busy="true" aria-label="Loading">
    <div className="skeleton__block skeleton__block--tile" />
    <div className="skeleton__block" />
    <div className="skeleton__block" />
  </div>
);

export const Spinner = (): React.JSX.Element => <span className="spin" role="status" aria-label="Working" />;
