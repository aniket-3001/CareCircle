import type { ReactNode } from 'react';
import type { Loaded } from '../state';
import { Skeleton } from './Pill';

/** Shows the skeleton on the first load, an honest error if it failed, and the content otherwise (stale content stays while it refreshes). */
export function Async<T>({ state, children }: { state: Loaded<T>; children: (data: T) => ReactNode }): React.JSX.Element {
  if (state.data !== undefined) return <>{children(state.data)}</>;
  if (state.error) {
    return (
      <div className="card" role="alert">
        <h2 className="card__title">Something went wrong</h2>
        <p className="muted">{state.error}</p>
      </div>
    );
  }
  return <Skeleton />;
}
