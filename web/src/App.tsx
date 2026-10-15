import { Info, ShieldCheck } from 'lucide-react';
import { AnimatePresence, MotionConfig, motion } from 'motion/react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { Session } from './api/types';
import { Fabs } from './components/Fabs';
import { Sheet } from './components/Sheet';
import { TabBar, type TabId } from './components/TabBar';
import { ToastProvider } from './components/Toast';
import { levelVars, worstSeverity, type SeverityKey } from './design/levels';
import { nameOf } from './lib/format';
import { loadSession, saveSession } from './lib/session';
import { AddScreen } from './screens/AddScreen';
import { CircleScreen } from './screens/CircleScreen';
import { GraphScreen } from './screens/GraphScreen';
import { HistoryScreen } from './screens/HistoryScreen';
import { TodayScreen } from './screens/TodayScreen';
import { Welcome } from './screens/Welcome';
import { AppCtx, makeApi, type AppState } from './state';

const TABS: TabId[] = ['today', 'add', 'circle', 'graph', 'history'];
const fromHash = (): TabId => {
  const h = window.location.hash.replace('#/', '').replace('#', '');
  return (TABS as string[]).includes(h) ? (h as TabId) : 'today';
};

export function App(): React.JSX.Element {
  const [session, setSession] = useState<Session | null>(loadSession);
  const [tab, setTab] = useState<TabId>(fromHash);
  const [rev, setRev] = useState(0);
  const [warp, setWarp] = useState(0);
  const [about, setAbout] = useState(false);
  const [sev, setSev] = useState<SeverityKey>('none');

  const go = useCallback((t: TabId) => { setTab(t); window.history.replaceState(null, '', `#/${t}`); window.scrollTo({ top: 0 }); }, []);
  useEffect(() => { const f = () => setTab(fromHash()); window.addEventListener('hashchange', f); return () => window.removeEventListener('hashchange', f); }, []);

  const start = useCallback((s: Session) => { saveSession(s); setSession(s); setWarp(0); go('today'); }, [go]);
  const reset = useCallback(() => { saveSession(null); setSession(null); setAbout(false); setSev('none'); }, []);
  const actAs = useCallback((as: string) => setSession((cur) => { if (!cur) return cur; const s = { ...cur, as }; saveSession(s); return s; }), []);

  const state = useMemo<AppState | null>(() => session && {
    session, api: makeApi(session), rev, bump: () => setRev((r) => r + 1), warp, setWarp,
    now: () => Date.now() + warp * 3_600_000, go, leave: reset, actAs,
  }, [session, rev, warp, go, reset, actAs]);

  // the page takes the colour of the most serious thing the record flags (the "level" wash)
  useEffect(() => {
    if (!state) return;
    let live = true;
    state.api.check().then((c) => live && setSev(c.judgement.state === 'no_data' ? 'unrated' : worstSeverity(c)), () => undefined);
    return () => { live = false; };
  }, [state]);

  return (
    <MotionConfig reducedMotion="user">
      <ToastProvider>
        <div className="page" style={levelVars(session ? sev : 'none')}>
          <div className="shell">
            <div className="topline">
              <span className="wordmark">
                <span className="logo" aria-hidden="true"><ShieldCheck size={18} strokeWidth={2} /></span>
                Care Circle
              </span>
              <div className="topline-actions">
                {session && Object.keys(session.keys).length > 1 && (
                  <fieldset className="actors" style={{ margin: 0 }} aria-label="Acting as">
                    {Object.keys(session.keys).map((k) => (
                      <button key={k} type="button" className="actor" aria-pressed={k === session.as} onClick={() => actAs(k)}>
                        <span className="av" aria-hidden="true">{nameOf(k).charAt(0)}</span>
                        {nameOf(k)}
                      </button>
                    ))}
                  </fieldset>
                )}
                <button type="button" className="icon-btn" onClick={() => setAbout(true)} aria-label="About and safety">
                  <Info size={20} strokeWidth={1.75} aria-hidden="true" />
                </button>
              </div>
            </div>

            {state ? (
              <AppCtx.Provider value={state}>
                <main id="main">
                  <AnimatePresence mode="wait" initial={false}>
                    <motion.div key={tab} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }}>
                      {tab === 'today' && <TodayScreen />}
                      {tab === 'add' && <AddScreen />}
                      {tab === 'circle' && <CircleScreen />}
                      {tab === 'graph' && <GraphScreen />}
                      {tab === 'history' && <HistoryScreen />}
                    </motion.div>
                  </AnimatePresence>
                </main>
                <Fabs />
                <TabBar current={tab} onSelect={go} />
              </AppCtx.Provider>
            ) : (
              <main id="main"><Welcome onStart={start} /></main>
            )}
          </div>

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
              <dl className="meta">
                <div><dt>Interactions</dt><dd>DDInter 2.0, licence CC BY-NC-SA 4.0 (non-commercial). About a quarter of pairs have no severity and are shown as unrated.</dd></div>
                <div><dt>Enzyme paths</dt><dd>FDA drug-interaction index table (not exhaustive) plus a small list marked “curated (unverified)”.</dd></div>
                <div><dt>Demo people</dt><dd>Entirely synthetic.</dd></div>
                <div><dt>Design</dt><dd>Visual language from The Vayu Project (hrsh-kr/the-vayu-project).</dd></div>
              </dl>
            </section>
            <section>
              <h3>AI use</h3>
              <p>Built with substantial help from Claude via Claude Code. At runtime an optional Amazon Bedrock model only structures text that OCR or speech recognition already read; every line it quotes must appear in that text, and a person confirms every entry.</p>
            </section>
            {session && <button type="button" className="btn btn--soft" onClick={reset}>Leave this circle and start over</button>}
          </Sheet>
        </div>
      </ToastProvider>
    </MotionConfig>
  );
}
