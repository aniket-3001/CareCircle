import { HeartPulse, ShieldAlert, X } from 'lucide-react';
import { useState } from 'react';
import { Async } from './Async';
import { useToast } from './Toast';
import { title } from '../lib/format';
import { useApp, useLoad } from '../state';
import { tr } from '../lib/i18n';

/** Conditions (why medicines are taken, as the family says it) and allergies, the latter cross-checked against the medicines on record. A hit means ask. */
export function ProfileCard(): React.JSX.Element {
  const app = useApp();
  const toast = useToast();
  const prof = useLoad((a) => a.api.profile(), [app.rev]);
  const check = useLoad((a) => a.api.allergyCheck(), [app.rev]);
  const [cond, setCond] = useState('');
  const [alg, setAlg] = useState('');

  const run = async (fn: () => Promise<unknown>, ok: string): Promise<void> => {
    try { await fn(); toast(ok); app.bump(); } catch (e) { toast(e instanceof Error ? e.message : 'Could not save'); }
  };
  return (
    <section className="card" aria-labelledby="prof-title" data-testid="profile">
      <div className="card-head"><h2 id="prof-title">{tr('Conditions and allergies')}</h2><HeartPulse size={20} aria-hidden="true" /></div>
      <Async state={check}>
        {(c) => c.hits.length > 0 ? (
          <div className="banner banner--bad" role="alert" data-testid="allergy-hit">
            {c.hits.map((h, i) => <div key={i}><b>{h.allergy}</b> is recorded as an allergy, and {title(h.drug)} on record is {h.why}. Ask the prescriber or pharmacist.</div>)}
          </div>
        ) : <></>}
      </Async>
      <Async state={prof}>
        {(p) => (
          <div className="stack">
            <div className="chips" aria-label={tr('Conditions')}>
              {p.conditions.length === 0 && <span className="muted">{tr('No conditions recorded.')}</span>}
              {p.conditions.map((c) => <span key={c.id} className="fchip">{c.name} <button type="button" className="icon-btn" aria-label={`Remove ${c.name}`} onClick={() => void run(() => app.api.removeProfileItem(c.id), 'Removed')}><X size={12} aria-hidden="true" /></button></span>)}
            </div>
            <form className="row" onSubmit={(e) => { e.preventDefault(); void run(() => app.api.addCondition(cond), 'Condition added').then(() => setCond('')); }}>
              <input type="text" aria-label={tr('Add a condition')} value={cond} onChange={(e) => setCond(e.target.value)} placeholder={tr('Add a condition, e.g. Type 2 diabetes')} maxLength={80} />
              <button type="submit" className="btn btn--sm" disabled={!cond.trim()}>{tr('Add')}</button>
            </form>
            <div className="chips" aria-label={tr('Allergies')}>
              {p.allergies.length === 0 && <span className="muted">{tr('No allergies recorded.')}</span>}
              {p.allergies.map((a) => <span key={a.id} className="fchip"><ShieldAlert size={12} aria-hidden="true" /> {a.text} <button type="button" className="icon-btn" aria-label={`Remove ${a.text}`} onClick={() => void run(() => app.api.removeProfileItem(a.id), 'Removed')}><X size={12} aria-hidden="true" /></button></span>)}
            </div>
            <form className="row" onSubmit={(e) => { e.preventDefault(); void run(() => app.api.addAllergy(alg), 'Allergy added').then(() => setAlg('')); }}>
              <input type="text" aria-label={tr('Add an allergy')} value={alg} onChange={(e) => setAlg(e.target.value)} placeholder={tr('Add an allergy, e.g. Penicillin')} maxLength={80} />
              <button type="submit" className="btn btn--sm" disabled={!alg.trim()}>{tr('Add')}</button>
            </form>
            <p className="muted small">{check.data?.note}</p>
          </div>
        )}
      </Async>
    </section>
  );
}
