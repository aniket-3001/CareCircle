import { Bot, Check, ChevronDown, Copy, LogOut, ShieldAlert, Trash2, UserRound } from 'lucide-react';
import { useState } from 'react';
import type { CircleInfo, Invite, Member } from '../api/types';
import { Async } from '../components/Async';
import { CircleForms } from '../components/CircleForms';
import { PageHead } from '../components/PageHead';
import { Pill } from '../components/Pill';
import { Sheet } from '../components/Sheet';
import { useToast } from '../components/Toast';
import { when } from '../lib/format';
import { useApp, useLoad } from '../state';

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
        <PageHead crumb="Account" title="No account" lede="You are in the throw-away demo, which has no account. Leave it and create an account to keep your circles." />
        <button type="button" className="btn" style={{ marginTop: 16 }} onClick={app.leave}>Leave the demo</button>
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
      <PageHead crumb="Account" title={p.name} lede={`${p.email} · ${p.provider === 'cognito' ? 'signed in with Amazon Cognito' : 'email and password'} · member since ${when(p.created_at)}`} />
      <div className="layout" style={{ marginTop: 18 }}>
        <div className="col">
          <section className="card" aria-labelledby="prof-title">
            <div className="row"><UserRound size={20} strokeWidth={1.75} aria-hidden="true" /><h2 id="prof-title">Profile</h2>{p.demo && <Pill tone="info">demo account</Pill>}</div>
            <label className="field">Your name (other carers see it)
              <input type="text" value={name ?? p.name} onChange={(e) => setName(e.target.value)} maxLength={60} />
            </label>
            <div className="row">
              <button type="button" className="btn btn--sm" disabled={name === null || !name.trim() || name === p.name} onClick={() => void save()}><Check size={16} aria-hidden="true" /> Save</button>
            </div>
            {p.demo && <p className="muted small">The demo accounts are shared by everyone, so their circle and name can be changed by anyone who uses them.</p>}
          </section>

          <section className="card" aria-labelledby="circ-title">
            <div className="card-head"><h2 id="circ-title">Your circles</h2><Pill tone="info">{p.circles.length}</Pill></div>
            {p.circles.length === 0 ? <p className="muted">You are not in a circle yet. Create one or join with a code below.</p> : (
              <div className="rows">
                {p.circles.map((c) => <CircleRow key={c.id} c={c} />)}
              </div>
            )}
          </section>
          <CircleForms />
        </div>

        <div className="col">
          <section className="card" aria-labelledby="tg-title">
            <div className="row"><Bot size={20} strokeWidth={1.75} aria-hidden="true" /><h2 id="tg-title">Telegram</h2>{p.telegram.length > 0 && <Pill tone="ok">linked</Pill>}</div>
            <p className="muted">Add medicines by sending a photo, a voice note or text to the bot, and get reminders in the chat. It uses this account and the circle you pick.</p>
            {p.telegram.length > 0 && (
              <div className="rows">
                {p.telegram.map((t) => <div key={t.chat} className="item"><div><div className="item__title">Chat {t.chat}</div><div className="item__sub">{p.circles.find((c) => c.id === t.circle)?.name ?? t.circle}</div></div></div>)}
                <button type="button" className="btn btn--ghost btn--sm" style={{ justifySelf: 'start', color: '#b0413e' }} onClick={() => void acct.telegramUnlink().then(app.refreshProfile).then(() => toast('Telegram unlinked'))}>Unlink Telegram</button>
              </div>
            )}
            {tg ? (
              <div className="banner" role="status" data-testid="tg-code">
                <div>Open <a href={`https://t.me/${BOT}`} target="_blank" rel="noreferrer">@{BOT}</a> and send:<br /><b className="tnum" style={{ fontSize: 20 }}>/link {tg.code}</b><br /><span className="small">The code works once, for {tg.minutes} minutes.</span></div>
              </div>
            ) : (
              <button type="button" className="btn btn--soft" onClick={() => void acct.telegramCode().then(setTg, (e) => toast(e instanceof Error ? e.message : 'Could not make a code'))}>Link Telegram</button>
            )}
          </section>

          {p.provider === 'local' && <PasswordCard />}

          <section className="card" aria-labelledby="sess-title">
            <h2 id="sess-title">Session</h2>
            <div className="row row--wrap">
              <button type="button" className="btn btn--soft" onClick={() => void app.signOut()}><LogOut size={18} aria-hidden="true" /> Sign out</button>
              {p.demo && <button type="button" className="btn btn--soft" onClick={() => void acct.resetDemo().then(() => { app.bump(); toast('The demo circle is back to its starting point.'); }, (e) => toast(e.message))}>Reset demo data</button>}
              {p.demo && <p className="muted small" style={{ flexBasis: '100%' }}>Reset demo data puts the shared demo circle (Asha) back to its starting medicines and history. Real circles are never affected.</p>}
            </div>
          </section>

          {!p.demo && (
            <section className="card" aria-labelledby="del-title">
              <div className="row"><ShieldAlert size={20} strokeWidth={1.75} aria-hidden="true" /><h2 id="del-title">Delete my account</h2></div>
              <p className="muted">Deletes your account, your sessions and every circle you are the only member of, with everything recorded in it. Circles with other carers stay, and the longest-standing carer becomes their owner. This cannot be undone.</p>
              <button type="button" className="btn btn--soft" style={{ color: '#b0413e', justifySelf: 'start' }} onClick={() => setSure(true)}><Trash2 size={18} aria-hidden="true" /> Delete my account…</button>
            </section>
          )}
        </div>
      </div>

      <Sheet open={sure} title="Delete your account?" onClose={() => setSure(false)}>
        <p>Type your email address, {p.email}, to confirm.</p>
        <label className="field">Email<input type="email" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="off" /></label>
        <button type="button" className="btn btn--danger" disabled={confirm.trim().toLowerCase() !== p.email} onClick={() => void deleteAccount()}>Delete everything</button>
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
          {app.session.circle === c.id ? <Pill tone="ok">open</Pill> : <button type="button" className="btn btn--soft btn--sm" onClick={() => { app.selectCircle(c.id); app.go('today'); }}>Open</button>}
          <button type="button" className="icon-btn" aria-expanded={open} aria-label={`${open ? 'Hide' : 'Show'} details of ${c.name}`} onClick={() => setOpen((o) => !o)}><ChevronDown size={18} aria-hidden="true" style={{ transform: open ? 'rotate(180deg)' : undefined, transition: 'transform 200ms' }} /></button>
        </div>
      </div>
      {open && (
        <div className="stack">
          <MemberList id={c.id} owner={owner} />
          {owner && (
            <>
              <div className="row row--wrap">
                <button type="button" className="btn btn--soft btn--sm" onClick={() => void acct.invite(c.id).then(setInvite, (e) => toast(e.message))}>Invite a carer</button>
                {invite && <span className="banner" data-testid="invite-code"><b className="tnum" style={{ fontSize: 18 }}>{invite.code}</b><button type="button" className="btn btn--ghost btn--sm" onClick={() => void navigator.clipboard?.writeText(invite.code).then(() => toast('Copied'))}><Copy size={14} aria-hidden="true" /> Copy</button><span className="small">one use · {invite.hours} h</span></span>}
              </div>
              <div className="row">
                <label className="field grow"><span className="sr-only">Circle name</span><input type="text" value={name ?? c.name} onChange={(e) => setName(e.target.value)} maxLength={60} /></label>
                <button type="button" className="btn btn--soft btn--sm" disabled={name === null || !name.trim() || name === c.name} onClick={() => void acct.renameCircle(c.id, name!).then(() => { setName(null); return app.refreshProfile(); }, (e) => toast(e.message))}>Rename</button>
              </div>
            </>
          )}
          <button type="button" className="btn btn--ghost btn--sm" style={{ justifySelf: 'start', color: '#b0413e' }} onClick={() => setLeaving(true)}>Leave this circle</button>
        </div>
      )}
      <Sheet open={leaving} title={`Leave ${c.name}?`} onClose={() => setLeaving(false)}>
        <p>{c.members === 1 ? 'You are the only carer, so leaving deletes the circle and everything recorded in it.' : owner ? 'You are the owner. Ownership passes to the carer who has been here longest.' : 'You will no longer see this circle. What you recorded stays for the other carers; your conversation with the helper is deleted.'}</p>
        <button type="button" className="btn btn--danger" onClick={() => void acct.leave(c.id).then(async () => { setLeaving(false); await app.refreshProfile(); toast('You left the circle.'); }, (e) => toast(e.message))}>Leave</button>
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
              {owner && !x.you && <button type="button" className="btn btn--ghost btn--sm" style={{ color: '#b0413e' }} onClick={() => void app.acct!.remove(id, x.id).then(() => { app.bump(); return app.refreshProfile(); }, (e) => toast(e.message))}>Remove</button>}
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
  return (
    <form className="card" aria-labelledby="pw-title" onSubmit={(e) => { e.preventDefault(); void app.acct!.changePassword(old, next).then(() => { toast('Password changed. Other devices must sign in again.'); setOld(''); setNext(''); }, (er) => toast(er.message)); }}>
      <h2 id="pw-title">Change password</h2>
      <label className="field">Current password<input type="password" value={old} onChange={(e) => setOld(e.target.value)} autoComplete="current-password" /></label>
      <label className="field">New password<input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" /></label>
      <div className="row"><button type="submit" className="btn btn--soft btn--sm" disabled={!old || next.length < 8}>Change password</button></div>
    </form>
  );
}

