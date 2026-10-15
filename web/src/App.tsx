import { Info, LogOut, ShieldCheck } from 'lucide-react';
import { AnimatePresence, MotionConfig, motion } from 'motion/react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { Profile, Session } from './api/types';
import { Assistant } from './components/Assistant';
import { Fabs } from './components/Fabs';
import { Skeleton } from './components/Pill';
import { Sheet } from './components/Sheet';
import { TabBar } from './components/TabBar';
import { ToastProvider } from './components/Toast';
import { levelVars, worstSeverity, type SeverityKey } from './design/levels';
import { nameOf } from './lib/format';
import { loadSession, saveSession } from './lib/session';
import { AccountScreen } from './screens/AccountScreen';
import { AddScreen } from './screens/AddScreen';
import { CircleScreen } from './screens/CircleScreen';
import { GraphScreen } from './screens/GraphScreen';
import { HistoryScreen } from './screens/HistoryScreen';
import { Onboarding } from './screens/Onboarding';
import { TodayScreen } from './screens/TodayScreen';
import { Welcome } from './screens/Welcome';
import { AppCtx, makeAccountApi, makeApi, type AppState, type TabId } from './state';

const TABS: TabId[] = ['today', 'add', 'circle', 'graph', 'history', 'account'];
const fromHash = (): TabId => {
  const h = window.location.hash.replace('#/', '').replace('#', '');
  return (TABS as string[]).includes(h) ? (h as TabId) : 'today';
};

export function App(): React.JSX.Element {
  const [session, setSession] = useState<Session | null>(loadSession);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabId>(fromHash);
  const [rev, setRev] = useState(0);
  const [warp, setWarp] = useState(0);
  const [about, setAbout] = useState(false);
  const [assistant, setAssistant] = useState<{ open: boolean; q?: string }>({ open: false });
  const [sev, setSev] = useState<SeverityKey>('none');
  const [welcomeReq, setWelcomeReq] = useState<{ view: 'signin' | 'signup'; n: number } | undefined>();
  const openAuth = (view: 'signin' | 'signup') => { setWelcomeReq((r) => ({ view, n: (r?.n ?? 0) + 1 })); window.scrollTo({ top: 0 }); };

  // each tab is a history entry, so Back walks through the tabs you visited before it leaves the app
  const go = useCallback((t: TabId) => {
    setTab(t);
    if (window.location.hash !== `#/${t}`) window.history.pushState(null, '', `#/${t}`);
    window.scrollTo({ top: 0 });
  }, []);
  useEffect(() => { const f = () => setTab(fromHash()); window.addEventListener('popstate', f); window.addEventListener('hashchange', f); return () => { window.removeEventListener('popstate', f); window.removeEventListener('hashchange', f); }; }, []);

  const token = session?.account ? session.keys.me ?? null : null;
  const acct = useMemo(() => (token ? makeAccountApi(token) : null), [token]);

  const persist = useCallback((s: Session | null) => { saveSession(s); setSession(s); }, []);
  const reset = useCallback(() => { persist(null); setProfile(null); setProfileError(null); setAbout(false); setAssistant({ open: false }); setSev('none'); setWarp(0); }, [persist]);

  const signOut = useCallback(async () => {
    if (session?.account) {
      await fetch('/v1/auth/signout', { method: 'POST', headers: { authorization: `Bearer ${session.keys.me}` } }).catch(() => undefined);
      if (session.account.provider === 'cognito' && session.account.tokens) {
        const { cognito } = await import('./lib/cognito');
        const cfg = await fetch('/v1/auth/config').then((r) => r.json() as Promise<{ cognito: { region: string; userPoolId: string; clientId: string } | null }>).catch(() => null);
        if (cfg?.cognito) await cognito(cfg.cognito).signOut(session.account.tokens.accessToken).catch(() => undefined);
      }
    }
    reset();
  }, [session, reset]);

  /** Everything about the account (name, circles, roles, linked chats) is read from the server; nothing is cached across sign-ins. */
  const refreshProfile = useCallback(async () => {
    if (!acct) return;
    try {
      const p = await acct.profile();
      setProfile(p);
      setProfileError(null);
      setSession((cur) => {
        if (!cur || !cur.account) return cur;
        if (p.circles.some((c) => c.id === cur.circle)) return cur;
        const first = p.circles[0];
        const s = { ...cur, circle: first?.id ?? '', person: first?.person ?? '' };
        saveSession(s);
        return s;
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Could not load your account';
      if (/invalid api key|401/i.test(msg)) { reset(); return; }          // the session ended: back to sign in
      setProfileError(msg);
    }
  }, [acct, reset]);
  useEffect(() => { void refreshProfile(); }, [refreshProfile]);

  const start = useCallback((s: Session) => { persist(s); setProfile(null); setWarp(0); go('today'); }, [persist, go]);
  const selectCircle = useCallback((id: string) => {
    const c = profile?.circles.find((x) => x.id === id);
    if (!c) return;
    setSession((cur) => { if (!cur) return cur; const s = { ...cur, circle: c.id, person: c.person }; saveSession(s); return s; });
    setWarp(0);
    setRev((r) => r + 1);
  }, [profile]);
  const actAs = useCallback((as: string) => setSession((cur) => { if (!cur) return cur; const s = { ...cur, as }; saveSession(s); return s; }), []);

  const circle = profile?.circles.find((c) => c.id === session?.circle) ?? null;
  const ready = !!session && (!acct || profile !== null);

  const state = useMemo<AppState | null>(() => session && {
    session, me: profile?.id ?? session.as, api: makeApi(session), acct, profile, circle, refreshProfile, selectCircle,
    rev, bump: () => setRev((r) => r + 1), warp, setWarp, isDemo: !!session.demoCircle || !!circle?.demo,
    now: () => Date.now() + warp * 3_600_000, go, leave: reset, signOut, actAs, askAssistant: (q?: string) => setAssistant({ open: true, q }),
  }, [session, acct, profile, circle, refreshProfile, selectCircle, rev, warp, go, reset, signOut, actAs]);

  // the page takes the colour of the most serious thing the record flags (the "level" wash)
  useEffect(() => {
    if (!state || !session?.circle) return;
    let live = true;
    state.api.check().then((c) => live && setSev(c.judgement.state === 'no_data' ? 'unrated' : worstSeverity(c)), () => undefined);
    return () => { live = false; };
  }, [state, session?.circle]);

  const needsCircle = !!acct && profile !== null && !session?.circle;
  let screen: React.ReactNode = null;
  if (state && ready) {
    screen = needsCircle && tab !== 'account' ? <Onboarding /> : (
      <>
        {tab === 'today' && <TodayScreen />}
        {tab === 'add' && <AddScreen />}
        {tab === 'circle' && <CircleScreen />}
        {tab === 'graph' && <GraphScreen />}
        {tab === 'history' && <HistoryScreen />}
        {tab === 'account' && <AccountScreen />}
      </>
    );
  }

  return (
    <MotionConfig reducedMotion="user">
      <ToastProvider>
        <div className="page" style={levelVars(session && session.circle ? sev : 'none')}>
          <div className="shell">
            <div className="topline">
              <span className="wordmark">
                <span className="logo" aria-hidden="true"><ShieldCheck size={18} strokeWidth={2} /></span>
                Care Circle
              </span>
              <div className="topline-actions">
                {profile && profile.circles.length > 0 && (
                  <label className="circle-pick">
                    <span className="sr-only">Circle</span>
                    <select value={session?.circle ?? ''} onChange={(e) => selectCircle(e.target.value)} data-testid="circle-picker">
                      {profile.circles.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                    </select>
                  </label>
                )}
                {session && !acct && Object.keys(session.keys).length > 1 && (
                  <fieldset className="actors" style={{ margin: 0 }} aria-label="Acting as">
                    {Object.keys(session.keys).map((k) => (
                      <button key={k} type="button" className="actor" aria-pressed={k === session.as} onClick={() => actAs(k)}>
                        <span className="av" aria-hidden="true">{nameOf(k).charAt(0)}</span>
                        {nameOf(k)}
                      </button>
                    ))}
                  </fieldset>
                )}
                {!session && (
                  <>
                    <button type="button" className="btn btn--ghost btn--sm" onClick={() => openAuth('signin')} data-testid="top-signin">Sign in</button>
                    <button type="button" className="btn btn--sm" onClick={() => openAuth('signup')} data-testid="top-signup" aria-label="Create account"><span className="wide-only">Create account</span><span className="narrow-only">Sign up</span></button>
                  </>
                )}
                {session && <button type="button" className="btn btn--ghost btn--sm" onClick={() => void signOut()} data-testid="top-signout"><LogOut size={16} aria-hidden="true" /> Sign out</button>}
                {profile && (
                  <button type="button" className="avatar-btn" onClick={() => go('account')} aria-label={`Account: ${profile.name}`} data-testid="open-account">
                    {profile.name.charAt(0).toUpperCase()}
                  </button>
                )}
                <button type="button" className="icon-btn" onClick={() => setAbout(true)} aria-label="About and safety">
                  <Info size={20} strokeWidth={1.75} aria-hidden="true" />
                </button>
              </div>
            </div>

            {session && state ? (
              <AppCtx.Provider value={state}>
                <main id="main">
                  {profileError && <div className="banner banner--bad" role="alert" style={{ marginTop: 16 }}>{profileError}</div>}
                  {ready ? (
                    <AnimatePresence mode="wait" initial={false}>
                      <motion.div key={needsCircle && tab !== 'account' ? 'onboarding' : tab} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }}>
                        {screen}
                      </motion.div>
                    </AnimatePresence>
                  ) : <div style={{ marginTop: 24 }}><Skeleton /></div>}
                </main>
                {ready && !needsCircle && <Fabs />}
                {ready && !needsCircle && <TabBar current={tab} onSelect={go} />}
                {ready && !needsCircle && <Assistant open={assistant.open} initial={assistant.q} onClose={() => setAssistant({ open: false })} />}
              </AppCtx.Provider>
            ) : (
              <main id="main"><Welcome onSession={start} request={welcomeReq} /></main>
            )}
          </div>

          <Sheet open={about} title="About and safety" onClose={() => setAbout(false)}>
            <section>
              <h3>What this is</h3>
              <p>A shared record of a person's medicines for the people who look after them. It records what carers add, cross-checks it against public data, and shows who has not seen a change.</p>
            </section>
            <section>
              <h3>What it will not do</h3>
              <p>It never tells anyone what to take, stop, skip or change. Flags are for discussion with a prescriber or pharmacist. No flag does not mean safe. The helper answers only from the record and refuses to advise.</p>
            </section>
            <section>
              <h3>Your data</h3>
              <p>Everything in an account (profile, circles, medicines, who has seen what, the helper conversation) is stored on the server, in a graph database, and you can export or delete it. Only a sign-in token is kept in this browser.</p>
            </section>
            <section>
              <h3>Where the data comes from</h3>
              <dl className="meta">
                <div><dt>Interactions</dt><dd>DDInter 2.0, licence CC BY-NC-SA 4.0 (non-commercial). About a quarter of pairs have no severity and are shown as unrated.</dd></div>
                <div><dt>Enzyme paths</dt><dd>FDA drug-interaction index table (not exhaustive) plus a small list marked “curated (unverified)”.</dd></div>
                <div><dt>Demo people</dt><dd>The demo accounts and the throw-away demo use made-up people. Circles you create contain only what you add.</dd></div>
                <div><dt>Design</dt><dd>Visual language from The Vayu Project (hrsh-kr/the-vayu-project).</dd></div>
              </dl>
            </section>
            <section>
              <h3>AI use</h3>
              <p>Built with substantial help from Claude via Claude Code. At runtime an optional Amazon Bedrock model structures text that OCR or speech recognition already read, and may phrase a helper answer from the record's facts; every quoted line must appear in the source text, answers are checked for advice and invented numbers, and a person confirms every entry.</p>
            </section>
          </Sheet>
        </div>
      </ToastProvider>
    </MotionConfig>
  );
}
