import { useState } from 'react';
import { startDemo } from '../api/client';
import type { Session } from '../api/types';
import { Spinner } from '../components/Pill';

export function Welcome({ onStart }: { onStart: (s: Session) => void }): React.JSX.Element {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [join, setJoin] = useState(false);
  const [circle, setCircle] = useState('');
  const [key, setKey] = useState('');
  const [person, setPerson] = useState('');

  async function start(): Promise<void> {
    setBusy(true);
    setErr('');
    try {
      onStart(await startDemo());
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Could not start the demo');
      setBusy(false);
    }
  }

  return (
    <div className="screen">
      <div className="hero">
        <div className="logo hero__logo" aria-hidden="true">C</div>
        <h1>One shared, verified memory of a loved one's medicines.</h1>
        <p>
          Care Circle keeps what each carer adds in one place, checks it against public interaction data, and tells everyone who has not yet seen a change.
          It records and cross-checks. It never says what to take or stop.
        </p>
        <div className="row row--wrap" style={{ justifyContent: 'center' }}>
          <button type="button" className="button" disabled={busy} onClick={() => void start()} data-testid="start-demo">Start a demo circle</button>
          <button type="button" className="button button--secondary" onClick={() => setJoin((j) => !j)}>I have a key</button>
          {busy && <Spinner />}
        </div>
        {err && <div className="banner" role="alert" style={{ background: 'var(--bad-bg)', color: 'var(--bad)' }}>{err}</div>}
        <p className="muted">All demo data is synthetic. No real people or records.</p>
      </div>

      {join && (
        <section className="card">
          <h2 className="card__title">Join an existing circle</h2>
          <div className="grid-2">
            <label className="field">Circle<input type="text" value={circle} onChange={(e) => setCircle(e.target.value)} /></label>
            <label className="field">Person cared for<input type="text" value={person} onChange={(e) => setPerson(e.target.value)} /></label>
            <label className="field">Your key<input type="password" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" /></label>
          </div>
          <button type="button" className="button" disabled={!circle || !key || !person} onClick={() => onStart({ circle: circle.trim(), person: person.trim().toLowerCase(), keys: { you: key.trim() }, as: 'you' })}>Open</button>
        </section>
      )}

      <section className="card">
        <h2 className="card__title">What you can try in two minutes</h2>
        <ol className="steps">
          <li>Open <b>Add</b>, press “Use a sample label”: a photo is read and shown with the exact line it came from.</li>
          <li>Confirm it. <b>Today</b> flags clarithromycin with atorvastatin as a major interaction, with its source and path.</li>
          <li>Open <b>Graph</b> and click nodes: every one explains itself in plain words.</li>
          <li>In <b>Circle</b>, Meena has not seen the change. Move the time warp to +13 h and a reminder appears.</li>
        </ol>
      </section>
    </div>
  );
}
