import type { ReactNode } from 'react';
import { useApp, type Loaded } from '../state';
import { Skeleton } from './Pill';

/** Shows the skeleton on the first load, an honest error if it failed, and the content otherwise (stale content stays while it refreshes). */
export function Async<T>({ state, children }: { state: Loaded<T>; children: (data: T) => ReactNode }): React.JSX.Element {
  const app = useApp();
  if (state.data !== undefined) return <>{children(state.data)}</>;
  if (state.error) {
    const gone = /invalid api key|not found|no access|not granted|forbidden/i.test(state.error);
    return (
      <div className="card" role="alert">
        <h2 className="card__title">{gone ? 'This circle is not available any more' : 'Something went wrong'}</h2>
        <p className="muted">{gone ? 'Demo circles are cleaned up after a while, or the key was changed. Nothing here can be recovered, but you can start a fresh demo.' : state.error}</p>
        {gone && <button type="button" className="button" style={{ justifySelf: 'start' }} onClick={app.leave}>Start over</button>}
      </div>
    );
  }
  return <Skeleton />;
}
