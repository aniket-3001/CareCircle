import { Bot, Check, ChevronDown, Copy, Download, LogOut, ShieldAlert, Trash2, UserRound } from 'lucide-react';
import { useState } from 'react';
import type { CircleInfo, Invite, Member } from '../api/types';
import { DisplayCard } from '../components/DisplayCard';
import { QuietHours } from '../components/QuietHours';
import { PasswordInput } from '../components/PasswordInput';
import { Async } from '../components/Async';
import { CircleForms } from '../components/CircleForms';
import { PageHead } from '../components/PageHead';
import { Pill } from '../components/Pill';
import { PharmacistLink } from '../components/PharmacistLink';
import { Sheet } from '../components/Sheet';
import { useToast } from '../components/Toast';
import { when } from '../lib/format';
import { useApp, useLoad } from '../state';
import { tr } from '../lib/i18n';
import { PushToggle } from '../components/PushToggle';

const BOT = 'CareCircleHelperBot';

export function AccountScreen(): React.JSX.Element {
  const app = useApp();
  const toast = useToast();
  const p = app.profile;
  const [name, setName] = useState<string | null>(null);
  const [sure, setSure] = useState(false);
  const [confirm, setConfirm] = useState('');
  const [tg, setTg] = useState<{ code: string; minutes: number } | null>(null);

  if (!app.acct || !p) {
    return (
      <div className="screen">
        <PageHead crumb={tr('Account')} title={tr('No account')} lede={tr('You are in the throw-away demo, which has no account. Leave it and create an account to keep your circles.')} />
        <button type="button" className="btn" style={{ marginTop: 16 }} onClick={app.leave}>{tr('Leave the demo')}</button>
      </div>
    );
  }
  const acct = app.acct;

  async function save(): Promise<void> {
    if (name === null) return;
    try {
      await acct.rename(name);
      await app.refreshProfile();
      setName(null);
      toast('Saved');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not save');
    }
  }

  /** Everything held for this account, as one JSON file the person keeps. */
  async function downloadAll(): Promise<void> {
    try {
      const doc = await acct.exportAll();
      const url = URL.createObjectURL(new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' }));
      const a = document.createElement('a');
      a.href = url; a.download = `care-circle-my-data-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) { toast(e instanceof Error ? e.message : 'Could not prepare the download'); }
  }
  async function deleteAccount(): Promise<void> {
    try {
      await acct.deleteAccount(confirm);
      if (app.session.account?.provider === 'cognito' && app.session.account.tokens) {
        const { cognito } = await import('../lib/cognito');
        const cfg = await fetch('/v1/auth/config').then((r) => r.json() as Promise<{ cognito: { region: string; userPoolId: string; clientId: string } | null }>);
        if (cfg.cognito) {
          const c = cognito(cfg.cognito);
          const t = await c.refresh(app.session.account.tokens.refreshToken).catch(() => app.session.account!.tokens!);
          await c.deleteUser(t.accessToken).catch(() => undefined);
        }
      }
      toast('Your account and its data are deleted.');
      app.leave();
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not delete the account');
    }
  }

  return (
    <div className="screen">
      <PageHead crumb={tr('Account')} title={p.name} lede={`${p.email} · ${p.provider === 'cognito' ? 'signed in with Amazon Cognito' : 'email and password'} · member since ${when(p.created_at)}`} />
      <div className="layout" style={{ marginTop: 18 }}>
        <div className="col">
          <section className="card" aria-labelledby="prof-title">
            <div className="row"><UserRound size={20} strokeWidth={1.75} aria-hidden="true" /><h2 id="prof-title">{tr('Profile')}</h2>{p.demo && <Pill tone="info">demo account</Pill>}</div>
            <label className="field">{tr('Your name (other carers see it)')}
              <input type="text" value={name ?? p.name} onChange={(e) => setName(e.target.value)} maxLength={60} disabled={!!p.demo} />
            </label>
            <div className="row">
              <button type="button" className="btn btn--sm" disabled={!!p.demo || name === null || !name.trim() || name === p.name} onClick={() => void save()}><Check size={16} aria-hidden="true" /> {tr('Save')}</button>
            </div>
            {p.demo && <p className="muted small">{tr('The demo accounts are shared by everyone, so their name and password cannot be changed. Create your own account to do that.')}</p>}
          </section>

          <PushToggle />
          <section className="card" aria-labelledby="circ-title">
            <div className="card-head"><h2 id="circ-title">{tr('Your circles')}</h2><Pill tone="info">{p.circles.length}</Pill></div>
            {p.circles.length === 0 ? <p className="muted">{tr('You are not in a circle yet. Create one or join with a code below.')}</p> : (
              <div className="rows">
                {p.circles.map((c) => <CircleRow key={c.id} c={c} />)}
              </div>
            )}
          </section>
          <CircleForms />
        </div>

        <div className="col">
          <section className="card" aria-labelledby="tg-title">
            <div className="row"><Bot size={20} strokeWidth={1.75} aria-hidden="true" /><h2 id="tg-title">{tr('Telegram')}</h2>{p.telegram.length > 0 && <Pill tone="ok">linked</Pill>}</div>
            <p className="muted">{tr('Add medicines by sending a photo, a voice note or text to the bot, and get reminders in the chat. It uses this account and the circle you pick.')}</p>
            {p.telegram.length > 0 && (
              <div className="rows">
                {p.telegram.map((t) => <div key={t.chat} className="item"><div><div className="item__title">Chat {t.chat}</div><div className="item__sub">{p.circles.find((c) => c.id === t.circle)?.name ?? t.circle}</div></div></div>)}
                <button type="button" className="btn btn--ghost btn--sm" style={{ justifySelf: 'start', color: 'var(--danger)' }} onClick={() => void acct.telegramUnlink().then(() => setTg(null)).then(app.refreshProfile).then(() => toast('Telegram unlinked'))}>{tr('Unlink Telegram')}</button>
              </div>
            )}
            {p.telegram.length === 0 && (tg ? (
              <div className="banner" role="status" data-testid="tg-code">
                <div>{tr('Open')} <a href={`https://t.me/${BOT}`} target="_blank" rel="noreferrer">@{BOT}</a> and send:<br /><b className="tnum" style={{ fontSize: 20 }}>/link {tg.code}</b><br /><span className="small">The code works once, for {tg.minutes} minutes.</span></div>
              </div>
            ) : (
              <button type="button" className="btn btn--soft" onClick={() => void acct.telegramCode().then(setTg, (e) => toast(e instanceof Error ? e.message : 'Could not make a code'))}>{tr('Link Telegram')}</button>
            ))}
          </section>

          {!p.demo && <QuietHours />}

          <DisplayCard />

          {!p.demo && <PasswordCard />}

          <section className="card" aria-labelledby="sess-title">
            <h2 id="sess-title">{tr('Session')}</h2>
            <div className="row row--wrap">
              <button type="button" className="btn btn--soft" onClick={() => void app.signOut()}><LogOut size={18} aria-hidden="true" /> {tr('Sign out')}</button>
              {!p.demo && <button type="button" className="btn btn--soft" onClick={() => void acct.signOutAll().then(() => app.signOut(), (e) => toast(e.message))} data-testid="signout-all">{tr('Sign out of all devices')}</button>}
              {!p.demo && <button type="button" className="btn btn--soft" onClick={() => void downloadAll()} data-testid="download-all"><Download size={18} aria-hidden="true" /> {tr('Download all my data')}</button>}
              {p.demo && <button type="button" className="btn btn--soft" onClick={() => void acct.resetDemo().then(() => { app.bump(); toast('The demo circle is back to its starting point.'); }, (e) => toast(e.message))}>{tr('Reset demo data')}</button>}
              {p.demo && <p className="muted small" style={{ flexBasis: '100%' }}>{tr('Reset demo data puts the shared demo circle (Asha) back to its starting medicines and history. Real circles are never affected.')}</p>}
            </div>
          </section>

          {!p.demo && (
            <section className="card" aria-labelledby="del-title">
              <div className="row"><ShieldAlert size={20} strokeWidth={1.75} aria-hidden="true" /><h2 id="del-title">{tr('Delete my account')}</h2></div>
              <p className="muted">Deletes your account, your sessions and every circle you are the only member of, with everything recorded in it. Circles with other carers stay, and the longest-standing carer becomes their owner. This cannot be undone.</p>
              <button type="button" className="btn btn--soft" style={{ color: 'var(--danger)', justifySelf: 'start' }} onClick={() => setSure(true)}><Trash2 size={18} aria-hidden="true" /> {tr('Delete my account…')}</button>
            </section>
          )}
        </div>
      </div>

      <Sheet open={sure} title={tr('Delete your account?')} onClose={() => setSure(false)}>
        <p>Type your email address, {p.email}, to confirm.</p>
        <label className="field">{tr('Email')}<input type="email" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="off" /></label>
        <button type="button" className="btn btn--danger" disabled={confirm.trim().toLowerCase() !== p.email} onClick={() => void deleteAccount()}>{tr('Delete everything')}</button>
      </Sheet>
    </div>
  );
}

function CircleRow({ c }: { c: CircleInfo }): React.JSX.Element {
  const app = useApp();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [invite, setInvite] = useState<Invite | null>(null);
  const [name, setName] = useState<string | null>(null);
  const [leaving, setLeaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [typed, setTyped] = useState('');
  const acct = app.acct!;
  const owner = c.role === 'owner';

  return (
    <div className="stack" style={{ padding: '12px 0', borderTop: '1px solid var(--line)' }} data-testid="circle-row">
      <div className="row row--between row--wrap">
        <div>
          <div className="item__title">{c.name} {c.demo && <Pill tone="info">demo</Pill>}</div>
          <div className="item__sub">for {c.person} · {c.role} · {c.members} {c.members === 1 ? 'carer' : 'carers'}</div>
        </div>
        <div className="row">
          {app.session.circle === c.id ? <Pill tone="ok">open</Pill> : <button type="button" className="btn btn--soft btn--sm" onClick={() => { app.selectCircle(c.id); app.go('today'); }}>{tr('Open')}</button>}
          <button type="button" className="icon-btn" aria-expanded={open} aria-label={`${open ? 'Hide' : 'Show'} details of ${c.name}`} onClick={() => setOpen((o) => !o)}><ChevronDown size={18} aria-hidden="true" style={{ transform: open ? 'rotate(180deg)' : undefined, transition: 'transform 200ms' }} /></button>
        </div>
      </div>
      {open && (
        <div className="stack">
          <MemberList id={c.id} owner={owner} />
          {owner && <PharmacistLink circle={c.id} person={c.person} />}
          {owner && (
            <>
              <div className="row row--wrap">
                <button type="button" className="btn btn--soft btn--sm" onClick={() => void acct.invite(c.id).then(setInvite, (e) => toast(e.message))}>{tr('Invite a carer')}</button>
                {invite && <span className="banner" data-testid="invite-code"><b className="tnum" style={{ fontSize: 18 }}>{invite.code}</b><button type="button" className="btn btn--ghost btn--sm" onClick={() => void (navigator.clipboard?.writeText(invite.code).then(() => toast('Copied'), () => toast('Could not copy: select the code and copy it')) ?? toast('Select the code and copy it'))}><Copy size={14} aria-hidden="true" /> {tr('Copy')}</button><span className="small">one use · {invite.hours} h</span></span>}
              </div>
              <div className="row">
                <label className="field grow"><span className="sr-only">{tr('Circle name')}</span><input type="text" value={name ?? c.name} onChange={(e) => setName(e.target.value)} maxLength={60} /></label>
                <button type="button" className="btn btn--soft btn--sm" disabled={name === null || !name.trim() || name === c.name} onClick={() => void acct.renameCircle(c.id, name!).then(() => { setName(null); return app.refreshProfile(); }, (e) => toast(e.message))}>{tr('Rename')}</button>
              </div>
            </>
          )}
          <button type="button" className="btn btn--ghost btn--sm" style={{ justifySelf: 'start', color: 'var(--danger)' }} onClick={() => setLeaving(true)}>{tr('Leave this circle')}</button>
          {owner && <button type="button" className="btn btn--ghost btn--sm" style={{ justifySelf: 'start', color: 'var(--danger)' }} onClick={() => setDeleting(true)} data-testid="delete-circle">{tr('Delete this circle…')}</button>}
        </div>
      )}
      <Sheet open={deleting} title={`Delete ${c.name}?`} onClose={() => { setDeleting(false); setTyped(''); }}>
        <p>{tr('This removes the circle for every carer in it, with every medicine, reading, note and conversation. It cannot be undone. Type the circle name to confirm.')}</p>
        <label className="field">{tr('Circle name')}<input type="text" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" /></label>
        <button type="button" className="btn btn--danger" disabled={typed.trim().toLowerCase() !== c.name.trim().toLowerCase()} onClick={() => void acct.deleteCircle(c.id, typed).then(async () => { setDeleting(false); setTyped(''); await app.refreshProfile(); toast('The circle is deleted.'); }, (e) => toast(e.message))} data-testid="delete-circle-go">{tr('Delete the circle')}</button>
      </Sheet>
      <Sheet open={leaving} title={`Leave ${c.name}?`} onClose={() => setLeaving(false)}>
        <p>{c.members === 1 ? 'You are the only carer, so leaving deletes the circle and everything recorded in it.' : owner ? 'You are the owner. Ownership passes to the carer who has been here longest.' : 'You will no longer see this circle. What you recorded stays for the other carers; your conversation with the helper is deleted.'}</p>
        <button type="button" className="btn btn--danger" onClick={() => void acct.leave(c.id).then(async () => { setLeaving(false); await app.refreshProfile(); toast('You left the circle.'); }, (e) => toast(e.message))}>{tr('Leave')}</button>
      </Sheet>
    </div>
  );
}

function MemberList({ id, owner }: { id: string; owner: boolean }): React.JSX.Element {
  const app = useApp();
  const toast = useToast();
  const m = useLoad(() => app.acct!.members(id), [id]);
  return (
    <Async state={m}>
      {(list: Member[]) => (
        <div className="rows" data-testid="members">
          {list.map((x) => (
            <div key={x.id} className="item">
              <div><div className="item__title">{x.name}{x.you ? ' (you)' : ''}</div><div className="item__sub">{x.role} · since {when(x.since)}</div></div>
              {owner && !x.you && <button type="button" className="btn btn--ghost btn--sm" style={{ color: 'var(--danger)' }} onClick={() => void app.acct!.remove(id, x.id).then(() => { app.bump(); return app.refreshProfile(); }, (e) => toast(e.message))}>{tr('Remove')}</button>}
            </div>
          ))}
        </div>
      )}
    </Async>
  );
}

function PasswordCard(): React.JSX.Element {
  const app = useApp();
  const toast = useToast();
  const [old, setOld] = useState('');
  const [next, setNext] = useState('');
  const [busy, setBusy] = useState(false);
  const acc = app.session.account;

  async function change(): Promise<void> {
    setBusy(true);
    try {
      if (acc?.provider === 'cognito' && acc.tokens) {                          // Cognito holds this password: change it there with a fresh access token
        const { cognito } = await import('../lib/cognito');
        const cfg = await fetch('/v1/auth/config').then((r) => r.json() as Promise<{ cognito: { region: string; userPoolId: string; clientId: string } | null }>);
        if (!cfg.cognito) throw new Error('Password change is not available right now.');
        const c = cognito(cfg.cognito);
        const t = await c.refresh(acc.tokens.refreshToken).catch(() => acc.tokens!);
        await c.changePassword(t.accessToken, old, next);
        toast('Password changed.');
      } else {
        await app.acct!.changePassword(old, next);
        toast('Password changed. Other devices must sign in again.');
      }
      setOld(''); setNext('');
    } catch (er) {
      toast(er instanceof Error ? er.message : 'Could not change the password');
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="card" aria-labelledby="pw-title" data-testid="password-card" onSubmit={(e) => { e.preventDefault(); void change(); }}>
      <h2 id="pw-title">{tr('Change password')}</h2>
      <label className="field">{tr('Current password')}<PasswordInput value={old} onChange={setOld} autoComplete="current-password" required /></label>
      <label className="field">{tr('New password')}<PasswordInput value={next} onChange={setNext} autoComplete="new-password" required /></label>
      <p className="muted small">{tr('At least 8 characters.')}</p>
      <div className="row"><button type="submit" className="btn btn--soft btn--sm" disabled={busy || !old || next.length < 8}>{tr('Change password')}</button></div>
    </form>
  );
}

