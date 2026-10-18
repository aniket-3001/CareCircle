import { PasswordInput } from '../components/PasswordInput';
import { isEmail, suggestEmail } from '../lib/email';
import { ArrowLeft, KeyRound, Mail, Play, ShieldCheck, UserPlus, Users } from 'lucide-react';
import { motion } from 'motion/react';
import { useEffect, useState } from 'react';
import { ApiError, authConfig, exchangeCognito, signInLocal, signUpLocal, startDemo, type Signed } from '../api/client';
import type { AuthConfig, Session } from '../api/types';
import { FaceIcon } from '../components/Face';
import { PageHead } from '../components/PageHead';
import { Spinner } from '../components/Pill';
import { useT } from '../lib/i18n';
import { AuthError, cognito, type CognitoClient, type Tokens } from '../lib/cognito';

type View = 'start' | 'signin' | 'signup' | 'confirm' | 'forgot' | 'reset';

const sessionFrom = (s: Signed, provider: 'local' | 'cognito', tokens?: Tokens): Session => ({
  circle: '', person: '', keys: { me: s.token }, as: 'me', account: { provider, ...(tokens ? { tokens } : {}) },
});

/** What a signed-out visitor sees: a way in (email and password, with a code by email on Cognito), the demo accounts, and a way to look around first. */
export function Welcome({ onSession, request }: { onSession: (s: Session) => void; request?: { view: 'signin' | 'signup'; n: number } }): React.JSX.Element {
  const t = useT();
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [view, setView] = useState<View>('start');
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [problem, setProblem] = useState<string | undefined>();
  const [note, setNote] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);

  useEffect(() => { authConfig().then(setConfig, () => setProblem('Could not reach the server. Check your connection and reload.')); }, []);
  // the header's Sign in / Create account buttons open the matching form
  useEffect(() => { if (request) { setView(request.view); setProblem(undefined); setNote(undefined); setCode(''); } }, [request]);
  useEffect(() => {                                                    // sent back here because the session ended: say so
    try {
      const n = window.sessionStorage.getItem('cc-notice');
      if (n) { window.sessionStorage.removeItem('cc-notice'); setNote(n); }
    } catch { /* private window */ }
  }, []);
  const client: CognitoClient | null = config?.cognito ? cognito(config.cognito) : null;
  const go = (v: View) => { setView(v); setProblem(undefined); setNote(undefined); setCode(''); };
  const tidy = (e: unknown) => (e instanceof AuthError || e instanceof ApiError || e instanceof Error ? e.message : 'Something went wrong. Try again in a moment.');

  async function run(step: () => Promise<void>, onError?: (e: unknown) => boolean): Promise<void> {
    setBusy(true);
    setProblem(undefined);
    try {
      await step();
    } catch (e) {
      if (onError?.(e) !== true) setProblem(tidy(e));
    } finally {
      setBusy(false);
    }
  }

  /** Sign in at Cognito, then trade its ID token for our session (the server checks the signature and that the email is verified). */
  const cognitoSignIn = async () => {
    const tokens = await client!.signIn(email.trim(), password);
    onSession(sessionFrom(await exchangeCognito(tokens.idToken, name.trim()), 'cognito', tokens));
  };
  const localSignIn = async () => onSession(sessionFrom(await signInLocal(email.trim(), password), 'local'));

  const doSignIn = () => run(client ? cognitoSignIn : localSignIn, (e) => {
    if (e instanceof AuthError && e.code === 'UserNotConfirmedException') {
      void client?.resendCode(email.trim()).catch(() => undefined);
      setNote('We emailed you a new code.');
      setView('confirm');
      return true;
    }
    return false;
  });
  /** Stop a mistyped address before anything is sent to it: the code would go nowhere and the person would wait for it. */
  const checkEmail = (): void => {
    const hint = suggestEmail(email);
    if (hint) throw new Error(`That address looks mistyped. Did you mean ${hint}?`);
    if (!isEmail(email)) throw new Error('That email address looks incomplete. It needs a name, an @ and a domain such as gmail.com.');
  };
  const doSignUp = () => run(async () => {
    checkEmail();
    if (client) {
      await client.signUp(email.trim(), password);
      setNote(`We emailed a code to ${email.trim()}.`);
      setView('confirm');
    } else {
      onSession(sessionFrom(await signUpLocal(email.trim(), password, name.trim()), 'local'));
    }
  });
  const doConfirm = () => run(async () => {
    await client!.confirmSignUp(email.trim(), code.trim());
    await cognitoSignIn();
  });
  const doForgot = () => run(async () => {
    checkEmail();
    await client!.forgotPassword(email.trim());
    setNote(`If ${email.trim()} has an account, we emailed a code.`);
    setView('reset');
  });
  const doReset = () => run(async () => {
    await client!.confirmForgotPassword(email.trim(), code.trim(), password);
    setView('signin');
    setNote('Your password is changed. Sign in with it.');
  });
  // a demo account is an ordinary account: this fills the sign-in form and you press Sign in
  const demoAccount = (e: string, p: string) => { go('signin'); setEmail(e); setPassword(p); setNote('Demo account filled in. Press Sign in to continue.'); window.scrollTo({ top: 0 }); };
  const anonymous = () => run(async () => onSession(await startDemo()));

  const emailField = <label className="field">{t('Email')}<input type="email" value={email} autoComplete="email" inputMode="email" required onChange={(e) => setEmail(e.target.value)} /></label>;
  const nameField = <label className="field">{t('Your name')}<input type="text" value={name} autoComplete="name" onChange={(e) => setName(e.target.value)} placeholder={t('How other carers see you')} /></label>;
  const pwField = (label: string, ac: string) => <label className="field">{t(label)}<PasswordInput value={password} autoComplete={ac} required onChange={setPassword} /></label>;
  const codeField = <label className="field">{t('The code we emailed you')}<input value={code} inputMode="numeric" autoComplete="one-time-code" required onChange={(e) => setCode(e.target.value)} /></label>;
  const messages = (
    <>
      {problem && <div className="banner banner--bad" role="alert">{problem}</div>}
      {note && <div className="banner" role="status">{t(note)}</div>}
    </>
  );
  const submit = (fn: () => Promise<void>) => (e: React.FormEvent) => { e.preventDefault(); void fn(); };
  const back = <button type="button" className="btn btn--ghost btn--sm" style={{ justifySelf: 'start' }} onClick={() => go('start')}><ArrowLeft size={16} aria-hidden="true" /> {t('Back')}</button>;

  return (
    <div className="screen">
      <PageHead crumb="Shared memory for people who care" title="Care Circle" />
      <div className="layout">
        <div className="col">
          <motion.section className="hero" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} aria-labelledby="welcome-title">
            <div className="hero-top">
              <div className="badge"><ShieldCheck size={46} strokeWidth={1.5} aria-hidden="true" /></div>
              <div>
                <h2 id="welcome-title" className="hero-level">{t("One shared, verified memory of a loved one's medicines.")}</h2>
                <p className="hero-line">{t('Each carer adds what they know, the record is checked against public interaction data, and everyone is told what they have not yet seen.')}</p>
              </div>
              <FaceIcon face="happy" size={76} />
            </div>
            <p className="hero-fine">{t('It records and cross-checks. It never says what to take or stop.')}</p>
          </motion.section>

          <section className="card" aria-labelledby="auth-title" data-testid="auth">
            {view === 'start' && (
              <>
                <div className="card-head"><h2 id="auth-title">{t('Get started')}</h2>{(busy || !config) && <Spinner />}</div>
                {messages}
                <div className="tiles" style={{ gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }}>
                  <button type="button" className="tile" onClick={() => go('signin')} data-testid="open-signin">
                    <span className="ico"><Mail size={26} strokeWidth={1.75} aria-hidden="true" /></span><b>{t('Sign in')}</b><span>with your email</span>
                  </button>
                  <button type="button" className="tile" onClick={() => go('signup')} data-testid="open-signup">
                    <span className="ico"><UserPlus size={26} strokeWidth={1.75} aria-hidden="true" /></span><b>{t('Create an account')}</b><span>free, takes a minute</span>
                  </button>
                </div>
                <p className="muted small">{t('An account keeps your circles, records and conversations on the server, so they follow you to any phone or laptop.')}</p>
              </>
            )}

            {view === 'signin' && (
              <form className="stack" onSubmit={submit(doSignIn)}>
                {back}
                <h2 id="auth-title">{t('Sign in')}</h2>
                {emailField}
                {pwField('Password', 'current-password')}
                {messages}
                <button type="submit" className="btn" disabled={busy || !config}>{busy ? 'Signing in…' : 'Sign in'}</button>
                {client && <button type="button" className="btn btn--ghost btn--sm" style={{ justifySelf: 'start' }} onClick={() => go('forgot')}>{t('Forgot your password?')}</button>}
                <button type="button" className="btn btn--ghost btn--sm" style={{ justifySelf: 'start' }} onClick={() => go('signup')}>{t('New here? Create an account')}</button>
              </form>
            )}

            {view === 'signup' && (
              <form className="stack" onSubmit={submit(doSignUp)}>
                {back}
                <h2 id="auth-title">{t('Create an account')}</h2>
                {nameField}
                {emailField}
                {pwField('Password', 'new-password')}
                <p className="muted small">{config?.password_rule ?? 'At least 8 characters, with a letter and a number.'}</p>
                {messages}
                <button type="submit" className="btn" disabled={busy || !config}>{busy ? 'Creating…' : 'Create account'}</button>
                <button type="button" className="btn btn--ghost btn--sm" style={{ justifySelf: 'start' }} onClick={() => go('signin')}>{t('Already have one? Sign in')}</button>
              </form>
            )}

            {view === 'confirm' && (
              <form className="stack" onSubmit={submit(doConfirm)}>
                <h2 id="auth-title">{t('Check your email')}</h2>
                <p className="muted">Enter the code we sent to {email}.</p>
                {codeField}
                {messages}
                <button type="submit" className="btn" disabled={busy}>{busy ? 'Confirming…' : 'Confirm'}</button>
                <button type="button" className="btn btn--ghost btn--sm" style={{ justifySelf: 'start' }} onClick={() => { setView('signup'); setProblem(undefined); setNote(undefined); setCode(''); }} data-testid="wrong-email">{t('Wrong email? Change it')}</button>
                <button type="button" className="btn btn--ghost btn--sm" style={{ justifySelf: 'start' }} onClick={() => { void client?.resendCode(email.trim()).then(() => setNote('We emailed you a new code.'), (e) => setProblem(tidy(e))); }}>{t('Send a new code')}</button>
              </form>
            )}

            {view === 'forgot' && (
              <form className="stack" onSubmit={submit(doForgot)}>
                {back}
                <h2 id="auth-title">{t('Reset your password')}</h2>
                <p className="muted">{t('We will email a code to the address on your account.')}</p>
                {emailField}
                {messages}
                <button type="submit" className="btn" disabled={busy}>{t('Send the code')}</button>
              </form>
            )}

            {view === 'reset' && (
              <form className="stack" onSubmit={submit(doReset)}>
                <h2 id="auth-title">{t('Choose a new password')}</h2>
                {codeField}
                {pwField('New password', 'new-password')}
                {messages}
                <button type="submit" className="btn" disabled={busy}>{t('Change password')}</button>
              </form>
            )}
          </section>
        </div>

        <div className="col">
          {(config?.demo_accounts.length ?? 0) > 0 && (
            <section className="card" aria-labelledby="demo-title" data-testid="demo-accounts">
              <div className="card-head"><h2 id="demo-title">{t('Try a demo account')}</h2></div>
              <p className="muted">{t('Two carers who already share a circle for Asha. Sign in as one, then as the other in another window, to see how a change reaches the second carer. The password is public.')}</p>
              <div className="stack">
                {config!.demo_accounts.map((d) => (
                  <button key={d.email} type="button" className="btn btn--soft" disabled={busy} onClick={() => demoAccount(d.email, d.password)} data-testid={`demo-${d.name.toLowerCase()}`}>
                    <Users size={18} aria-hidden="true" /> {t('Sign in')}: {d.name} <span className="muted small">{d.email}</span>
                  </button>
                ))}
              </div>
            </section>
          )}
          <section className="card" aria-labelledby="anon-title">
            <div className="card-head"><h2 id="anon-title">{t('Just look around')}</h2></div>
            <p className="muted">{t('A throw-away circle with fake data and two carers you can switch between.')}</p>
            <button type="button" className="btn btn--soft" disabled={busy} onClick={() => void anonymous()} data-testid="start-demo"><Play size={18} aria-hidden="true" /> {t('Start a demo circle')}</button>
          </section>
          <section className="card">
            <h2>{t('What you can do in two minutes')}</h2>
            <ol className="steps">
              <li><span>{t('Add a medicine from a photo, a voice note, a document or by typing: each reading shows the exact line it came from.')}</span></li>
              <li><span>{t('See what the record flags, with its source, and open the graph to read why in plain words.')}</span></li>
              <li><span>{t('Invite another carer with a code and see who has not yet seen a change.')}</span></li>
              <li><span>{t('Ask the helper about the record, or link the Telegram bot to add things by chat.')}</span></li>
            </ol>
            <p className="muted small"><KeyRound size={14} aria-hidden="true" style={{ verticalAlign: '-2px' }} /> {t('Everything you add is saved on the server, never only in your browser.')}</p>
          </section>
        </div>
      </div>
    </div>
  );
}
