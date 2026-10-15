import { useCallback, useMemo, useState } from 'react';
import { makeApi, AppCtx, type AppState } from './state';
import type { Session } from './api/types';
import { Segmented } from './components/Segmented';
import { Sheet } from './components/Sheet';
import { TabBar, type TabId } from './components/TabBar';
import { ToastProvider } from './components/Toast';
import { nameOf } from './lib/format';
import { loadSession, saveSession } from './lib/session';
import { AddScreen } from './screens/AddScreen';
import { CircleScreen } from './screens/CircleScreen';
import { GraphScreen } from './screens/GraphScreen';
import { HistoryScreen } from './screens/HistoryScreen';
import { TodayScreen } from './screens/TodayScreen';
import { Welcome } from './screens/Welcome';

export function App(): React.JSX.Element {
  const [session, setSession] = useState<Session | null>(loadSession);
  const [tab, setTab] = useState<TabId>('today');
  const [rev, setRev] = useState(0);
  const [warp, setWarp] = useState(0);
  const [about, setAbout] = useState(false);

  const start = useCallback((s: Session) => { saveSession(s); setSession(s); setTab('today'); setWarp(0); }, []);
  const reset = useCallback(() => { saveSession(null); setSession(null); setAbout(false); }, []);

  const state = useMemo<AppState | null>(() => session && {
    session, api: makeApi(session), rev, bump: () => setRev((r) => r + 1), warp, setWarp,
    now: () => Date.now() + warp * 3_600_000, go: setTab, leave: reset,
  }, [session, rev, warp, reset]);

  return (
    <ToastProvider>
      <div className="app">
        <header className="navbar">
          <div className="navbar__row">
            <div>
              <h1 className="navbar__title"><span className="logo" aria-hidden="true">C</span> Care Circle</h1>
              <div className="navbar__sub">{session ? 'Synthetic data · records, never advises' : 'Shared memory for people who care'}</div>
            </div>
            <div className="row">
              {session && Object.keys(session.keys).length > 1 && (
                <Segmented name="actor" label="Acting as" value={session.as} options={Object.keys(session.keys).map((k) => ({ value: k, label: nameOf(k) }))}
                  onChange={(as) => { const s = { ...session, as }; saveSession(s); setSession(s); }} />
              )}
              <button type="button" className="button button--quiet" onClick={() => setAbout(true)} aria-label="About and safety">About</button>
            </div>
          </div>
        </header>

        {state ? (
          <AppCtx.Provider value={state}>
            <main id="main">
              {tab === 'today' && <TodayScreen />}
              {tab === 'add' && <AddScreen />}
              {tab === 'circle' && <CircleScreen />}
              {tab === 'graph' && <GraphScreen />}
              {tab === 'history' && <HistoryScreen />}
            </main>
            <TabBar current={tab} onSelect={setTab} />
          </AppCtx.Provider>
        ) : (
          <main id="main"><Welcome onStart={start} /></main>
        )}

        <Sheet open={about} title="About and safety" onClose={() => setAbout(false)}>
          <section>
            <h3>What this is</h3>
            <p>A shared record of a person's medicines for the people who look after them. It records what carers add, cross-checks it against public data, and shows who has not seen a change.</p>
          </section>
          <section>
            <h3>What it will not do</h3>
            <p>It never tells anyone what to take, stop, skip or change. Flags are for discussion with a prescriber or pharmacist. No flag does not mean safe.</p>
          </section>
          <section>
            <h3>Where the data comes from</h3>
            <dl>
              <dt>Interactions</dt><dd>DDInter 2.0, licence CC BY-NC-SA 4.0 (non-commercial). About a quarter of pairs have no severity and are shown as unrated.</dd>
              <dt>Enzyme paths</dt><dd>FDA drug-interaction index table (not exhaustive) plus a small list marked “curated (unverified)”.</dd>
              <dt>Demo people</dt><dd>Entirely synthetic.</dd>
            </dl>
          </section>
          <section>
            <h3>AI use</h3>
            <p>Built with substantial help from Claude via Claude Code. At runtime an optional Amazon Bedrock model only structures text that OCR or speech recognition already read; every line it quotes must appear in that text, and a person confirms every entry.</p>
          </section>
          {session && <button type="button" className="button button--secondary" onClick={reset}>Leave this circle and start over</button>}
        </Sheet>
      </div>
    </ToastProvider>
  );
}
