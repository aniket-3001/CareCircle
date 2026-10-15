import { LogIn, Plus } from 'lucide-react';
import { useState } from 'react';
import { Spinner } from './Pill';
import { useToast } from './Toast';
import { useApp } from '../state';
import { tr } from '../lib/i18n';

/** Create a circle, or join one with an invitation code. Both write to the server; the page then opens the circle. */
export function CircleForms({ onDone }: { onDone?: () => void }): React.JSX.Element {
  const app = useApp();
  const toast = useToast();
  const [name, setName] = useState('');
  const [person, setPerson] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState<'' | 'create' | 'join'>('');

  async function create(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    if (!app.acct) return;
    setBusy('create');
    try {
      const c = await app.acct.createCircle(name, person);
      await app.refreshProfile();
      app.selectCircle(c.id);
      toast(`Created ${c.name}. It starts empty: add the first medicine when you are ready.`);
      setName(''); setPerson('');
      onDone?.();
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Could not create the circle');
    } finally {
      setBusy('');
    }
  }

  async function join(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    if (!app.acct) return;
    setBusy('join');
    try {
      const c = await app.acct.join(code);
      await app.refreshProfile();
      app.selectCircle(c.id);
      toast(`You joined ${c.name}.`);
      setCode('');
      onDone?.();
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Could not join');
    } finally {
      setBusy('');
    }
  }

  return (
    <div className="layout layout--even" style={{ marginTop: 0 }}>
      <form className="card" onSubmit={create} aria-labelledby="new-circle-title" data-testid="new-circle">
        <h2 id="new-circle-title">{tr('Create a circle')}</h2>
        <p className="muted small">{tr('One circle looks after one person. You are its owner and can invite other carers.')}</p>
        <label className="field">{tr('Circle name')}<input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Mum's medicines" required maxLength={60} /></label>
        <label className="field">{tr('Person being looked after')}<input type="text" value={person} onChange={(e) => setPerson(e.target.value)} placeholder="e.g. Mum" required maxLength={40} /></label>
        <div className="row">
          <button type="submit" className="btn" disabled={!!busy || !name.trim() || !person.trim()}><Plus size={18} aria-hidden="true" /> {tr('Create')}</button>
          {busy === 'create' && <Spinner />}
        </div>
      </form>
      <form className="card" onSubmit={join} aria-labelledby="join-title" data-testid="join-circle">
        <h2 id="join-title">{tr('Join with a code')}</h2>
        <p className="muted small">{tr('Another carer can make a one-time invitation code for you on their Account page.')}</p>
        <label className="field">{tr('Invitation code')}<input type="text" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder={tr('ABCD-2345')} autoComplete="off" maxLength={12} required /></label>
        <div className="row">
          <button type="submit" className="btn btn--soft" disabled={!!busy || code.replace(/[^A-Za-z0-9]/g, '').length < 8}><LogIn size={18} aria-hidden="true" /> {tr('Join')}</button>
          {busy === 'join' && <Spinner />}
        </div>
      </form>
    </div>
  );
}
