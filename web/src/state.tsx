import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { accountApi, apiFor, type AccountApi, type Api } from './api/client';
import type { CircleInfo, Profile, Session } from './api/types';

export type TabId = 'today' | 'add' | 'circle' | 'graph' | 'history' | 'account';

export interface AppState {
  session: Session;
  /** The acting carer's agent id (an account's id, or the demo carer's), as the server records it. */
  me: string;
  api: Api;
  /** Account calls (profile, circles, invites). Null in the anonymous demo, which has no account. */
  acct: AccountApi | null;
  /** The signed-in person's profile, read from the server. Null in the anonymous demo. */
  profile: Profile | null;
  /** The circle that is open (name, role, members), read from the server. */
  circle: CircleInfo | null;
  /** Reload the profile and circles after a change. */
  refreshProfile: () => Promise<void>;
  selectCircle: (id: string) => void;
  /** Bumps after every change so screens reload. */
  rev: number;
  bump: () => void;
  /** Hours added to "now" by the time-warp control. Only offered in demo circles: a real record is always read as of now. */
  warp: number;
  setWarp: (h: number) => void;
  isDemo: boolean;
  now: () => number;
  go: (tab: TabId) => void;
  /** Forget this browser's session and return to the welcome screen. */
  leave: () => void;
  /** End the session on the server (and at Cognito), then return to the sign-in page. */
  signOut: () => Promise<void>;
  /** Switch which carer is acting (anonymous demo only). */
  actAs: (agent: string) => void;
  /** Open the helper assistant. */
  askAssistant: (question?: string) => void;
}

export const AppCtx = createContext<AppState | null>(null);
export const useApp = (): AppState => {
  const v = useContext(AppCtx);
  if (!v) throw new Error('useApp outside provider');
  return v;
};

export const makeApi = apiFor;
export const makeAccountApi = accountApi;

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
  const run = useCallback(fn, [app.rev, app.session.as, app.session.circle, ...deps]);
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
