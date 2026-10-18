import { Info, LogOut, Moon, ShieldCheck, Sun } from 'lucide-react';
import { AnimatePresence, MotionConfig, motion } from 'motion/react';
import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react';
import type { Profile, Session } from './api/types';
import { Assistant } from './components/Assistant';
import { Fabs } from './components/Fabs';
import { Help } from './components/Help';
import { Skeleton } from './components/Pill';
import { Sheet } from './components/Sheet';
import { TabBar } from './components/TabBar';
import { ToastProvider } from './components/Toast';
import { levelVars, worstSeverity, type SeverityKey } from './design/levels';
import { nameOf } from './lib/format';
import { setLang, useLang, useT } from './lib/i18n';
import { authHeaders } from './api/client';
import { loadSession, saveSession } from './lib/session';
import { setTheme, useTheme } from './lib/theme';
import { Onboarding } from './screens/Onboarding';
import { TodayScreen } from './screens/TodayScreen';
import { Welcome } from './screens/Welcome';
import { AppCtx, makeAccountApi, makeApi, type AppState, type TabId } from './state';

// The screens a person opens less often load when first opened, so the first screen arrives sooner on a slow connection.
const AccountScreen = lazy(() => import('./screens/AccountScreen').then((m) => ({ default: m.AccountScreen })));
const AddScreen = lazy(() => import('./screens/AddScreen').then((m) => ({ default: m.AddScreen })));
const CircleScreen = lazy(() => import('./screens/CircleScreen').then((m) => ({ default: m.CircleScreen })));
const GraphScreen = lazy(() => import('./screens/GraphScreen').then((m) => ({ default: m.GraphScreen })));
const HistoryScreen = lazy(() => import('./screens/HistoryScreen').then((m) => ({ default: m.HistoryScreen })));

const TABS: TabId[] = ['today', 'add', 'circle', 'graph', 'history', 'account'];
const fromHash = (): TabId => {
  const h = window.location.hash.replace('#/', '').replace('#', '');
  return (TABS as string[]).includes(h) ? (h as TabId) : 'today';
};

export function App(): React.JSX.Element {
  const t = useT();
  const lang = useLang();
  const theme = useTheme();
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
  const reset = useCallback(() => { persist(null); setProfile(null); setProfileError(null); setAbout(false); setAssistant({ open: false }); setSev('none'); setWarp(0); setWelcomeReq(undefined); }, [persist]);

  const signOut = useCallback(async () => {
    if (session?.account) {
      await fetch('/v1/auth/signout', { method: 'POST', headers: authHeaders(session.keys.me) }).catch(() => undefined);
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

  // any request that comes back 401 means this session is over (signed out on another device, password changed, expired): back to sign-in, with a word about why
  useEffect(() => {
    const onEnded = (): void => {
      try { window.sessionStorage.setItem('cc-notice', 'Your session has ended. Please sign in again.'); } catch { /* private window */ }
      reset();
    };
    window.addEventListener('cc-session-ended', onEnded);
    return () => window.removeEventListener('cc-session-ended', onEnded);
  }, [reset]);

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
      <Suspense fallback={<Skeleton />}>
        {tab === 'today' && <TodayScreen />}
        {tab === 'add' && <AddScreen />}
        {tab === 'circle' && <CircleScreen />}
        {tab === 'graph' && <GraphScreen />}
        {tab === 'history' && <HistoryScreen />}
        {tab === 'account' && <AccountScreen />}
      </Suspense>
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
                <span className="wide-only">{t('Care Circle')}</span>
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
                  <fieldset className="actors" style={{ margin: 0 }} aria-label={t('Acting as')}>
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
                    <button type="button" className="btn btn--ghost btn--sm" onClick={() => openAuth('signin')} data-testid="top-signin">{t('Sign in')}</button>
                    <button type="button" className="btn btn--sm" onClick={() => openAuth('signup')} data-testid="top-signup" aria-label="Create account"><span className="wide-only">{t('Create account')}</span><span className="narrow-only">{t('Sign up')}</span></button>
                  </>
                )}
                {session && <button type="button" className="btn btn--ghost btn--sm" onClick={() => void signOut()} data-testid="top-signout" aria-label={t('Sign out')}><LogOut size={16} aria-hidden="true" /><span className="wide-only"> {t('Sign out')}</span></button>}
                {profile && (
                  <button type="button" className="avatar-btn" onClick={() => go('account')} aria-label={`Account: ${profile.name}`} data-testid="open-account">
                    {profile.name.charAt(0).toUpperCase()}
                  </button>
                )}
                <button type="button" className="btn btn--ghost btn--sm lang-btn" onClick={() => setLang(lang === 'hi' ? 'en' : 'hi')} aria-label={t('Language')} title="English / हिन्दी" data-testid="lang-toggle">{lang === 'hi' ? 'EN' : 'हिं'}</button>
                <button type="button" className="icon-btn" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} aria-label={theme === 'dark' ? t('Switch to light theme') : t('Switch to dark theme')} title={theme === 'dark' ? t('Light theme') : t('Dark theme')} data-testid="theme-toggle">
                  {theme === 'dark' ? <Sun size={20} strokeWidth={1.75} aria-hidden="true" /> : <Moon size={20} strokeWidth={1.75} aria-hidden="true" />}
                </button>
                <button type="button" className="icon-btn" onClick={() => setAbout(true)} aria-label={t('About and safety')}>
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

          <Sheet open={about} title={t('About and safety')} onClose={() => setAbout(false)}>
            <section>
              <h3>{t('Help')}</h3>
              <Help />
            </section>
            <section>
              <h3>{t('What this is')}</h3>
              <p>{t("A shared record of a person's medicines for the people who look after them. It records what carers add, cross-checks it against public data, and shows who has not seen a change.")}</p>
            </section>
            <section>
              <h3>{t('What it will not do')}</h3>
              <p>{t('It never tells anyone what to take, stop, skip or change. No flag is not a guarantee of safety. The helper answers only from the record.')}</p>
            </section>
            <section>
              <h3>{t('Your data')}</h3>
              <p>Everything in an account (profile, circles, medicines, who has seen what, the helper conversation) is stored on the server, in a graph database. Only a sign-in token and your theme and language choice are kept in this browser.</p>
              <ul className="steps">
                <li><span><b>Who can see a circle:</b> only the people you invite into it. Each circle is its own graph, apart from accounts and from the public reference data.</span></li>
                <li><span><b>What leaves the server:</b> only a medicine name, to look up its label, recalls or ingredients on RxNorm and openFDA (US public services). Never a person's name, a dose or anything about who takes it. Text read from a photo or voice note may be sent to an Amazon Bedrock model to be tidied into entries, and you confirm every entry.</span></li>
                <li><span><b>Notifications:</b> if you turn on browser notifications, your browser's push address is stored so we can reach it. Linking Telegram stores your chat id. Both can be turned off in Account.</span></li>
                <li><span><b>Export and deletion:</b> History exports the record as FHIR JSON and can remove one entry or everything about a person, with a receipt. Delete my account removes the account, and any circle you were the last member of. Server backups are kept for up to 14 days, so deleted data can remain in a backup until it expires.</span></li>
                <li><span><b>Not for emergencies:</b> this is a record, not a medical service. It does not monitor anyone.</span></li>
              </ul>
            </section>
            <section>
              <h3>{t('Where the data comes from')}</h3>
              <dl className="meta">
                <div><dt>Interactions</dt><dd>DDInter 2.0, licence CC BY-NC-SA 4.0 (non-commercial). About a quarter of pairs have no severity and are shown as unrated.</dd></div>
                <div><dt>Enzyme paths</dt><dd>FDA drug-interaction index table (not exhaustive) plus a small list marked “curated (unverified)”.</dd></div>
                <div><dt>Demo people</dt><dd>{t('The demo accounts and the throw-away demo use made-up people. Circles you create contain only what you add.')}</dd></div>
              </dl>
            </section>
          </Sheet>
        </div>
      </ToastProvider>
    </MotionConfig>
  );
}
