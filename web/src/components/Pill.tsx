import type { ReactNode } from 'react';

export type Tone = 'ok' | 'minor' | 'warn' | 'bad' | 'info' | 'mute';

export const Pill = ({ tone = 'mute', children }: { tone?: Tone; children: ReactNode }): React.JSX.Element => <span className={`pill pill--${tone}`}>{children}</span>;

export const Skeleton = (): React.JSX.Element => (
  <div className="skeleton" aria-busy="true" aria-label="Loading">
    <i />
    <i />
  </div>
);

export const Spinner = (): React.JSX.Element => <span className="spin" role="status" aria-label="Working" />;
