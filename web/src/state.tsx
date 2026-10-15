import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { apiFor, type Api } from './api/client';
import type { Session } from './api/types';

export interface AppState {
  session: Session;
  api: Api;
  /** Bumps after every change so screens reload. */
  rev: number;
  bump: () => void;
  /** Hours added to "now" by the time-warp control, so reminders can be shown without waiting. */
  warp: number;
  setWarp: (h: number) => void;
  now: () => number;
  go: (tab: 'today' | 'add' | 'circle' | 'graph' | 'history') => void;
}

export const AppCtx = createContext<AppState | null>(null);
export const useApp = (): AppState => {
  const v = useContext(AppCtx);
  if (!v) throw new Error('useApp outside provider');
  return v;
};

export const makeApi = apiFor;

export interface Loaded<T> {
  data: T | undefined;
  error: string | undefined;
  loading: boolean;
}

/** Loads on mount and whenever the deps or the app revision change. A slow older response never overwrites a newer one. */
export function useLoad<T>(fn: (app: AppState) => Promise<T>, deps: unknown[] = []): Loaded<T> {
  const app = useApp();
  const [st, setSt] = useState<Loaded<T>>({ data: undefined, error: undefined, loading: true });
  const seq = useRef(0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(fn, [app.rev, app.session.as, ...deps]);
  useEffect(() => {
    const id = ++seq.current;
    setSt((s) => ({ ...s, loading: true }));
    run(app).then(
      (data) => id === seq.current && setSt({ data, error: undefined, loading: false }),
      (e: unknown) => id === seq.current && setSt({ data: undefined, error: e instanceof Error ? e.message : String(e), loading: false }),
    );
  }, [run, app]);
  return st;
}
