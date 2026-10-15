import { TriangleAlert } from 'lucide-react';
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
        <div className="row">
          <TriangleAlert size={22} strokeWidth={1.75} aria-hidden="true" />
          <h2>{gone ? 'This circle is not available any more' : 'Something went wrong'}</h2>
        </div>
        <p className="muted">{gone ? 'Demo circles are cleaned up after a while, or the key was changed. Nothing here can be recovered, but you can start a fresh demo.' : state.error}</p>
        {gone && (
          <button type="button" className="btn" style={{ justifySelf: 'start' }} onClick={app.leave}>
            Start over
          </button>
        )}
      </div>
    );
  }
  return <Skeleton />;
}
