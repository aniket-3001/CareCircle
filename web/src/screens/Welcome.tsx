import { KeyRound, Play, ShieldCheck } from 'lucide-react';
import { motion } from 'motion/react';
import { useState } from 'react';
import { startDemo } from '../api/client';
import type { Session } from '../api/types';
import { FaceIcon } from '../components/Face';
import { PageHead } from '../components/PageHead';
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
      <PageHead crumb="Shared memory for people who care" title="Care Circle" />
      <div className="layout">
        <div className="col">
          <motion.section className="hero" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} aria-labelledby="welcome-title">
            <div className="hero-top">
              <div className="badge">
                <ShieldCheck size={46} strokeWidth={1.5} aria-hidden="true" />
              </div>
              <div>
                <h2 id="welcome-title" className="hero-level">One shared, verified memory of a loved one's medicines.</h2>
                <p className="hero-line">Care Circle keeps what each carer adds in one place, checks it against public interaction data, and tells everyone who has not yet seen a change.</p>
              </div>
              <FaceIcon face="happy" size={76} />
            </div>
            <p className="hero-fine">It records and cross-checks. It never says what to take or stop. All demo data is synthetic: no real people or records.</p>
          </motion.section>
          <section className="card" aria-labelledby="start-title">
            <div className="card-head">
              <h2 id="start-title">Get started</h2>
              {busy && <Spinner />}
            </div>
            <div className="tiles" style={{ gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }}>
              <button type="button" className="tile" disabled={busy} onClick={() => void start()} data-testid="start-demo">
                <span className="ico"><Play size={26} strokeWidth={1.75} aria-hidden="true" /></span>
                <b>Start a demo circle</b>
                <span>Asha, with two carers</span>
              </button>
              <button type="button" className="tile" onClick={() => setJoin((j) => !j)}>
                <span className="ico"><KeyRound size={26} strokeWidth={1.75} aria-hidden="true" /></span>
                <b>I have a key</b>
                <span>Join an existing circle</span>
              </button>
            </div>
            {err && <div className="banner banner--bad" role="alert">{err}</div>}
            {join && (
              <div className="stack">
                <div className="grid-2">
                  <label className="field">Circle<input type="text" value={circle} onChange={(e) => setCircle(e.target.value)} /></label>
                  <label className="field">Person cared for<input type="text" value={person} onChange={(e) => setPerson(e.target.value)} /></label>
                  <label className="field">Your key<input type="password" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" /></label>
                </div>
                <div className="row">
                  <button type="button" className="btn" disabled={!circle || !key || !person} onClick={() => onStart({ circle: circle.trim(), person: person.trim().toLowerCase(), keys: { you: key.trim() }, as: 'you' })}>Open</button>
                </div>
              </div>
            )}
          </section>
        </div>
        <div className="col">
          <section className="card">
            <h2>What you can try in two minutes</h2>
            <ol className="steps">
              <li><span>Open <b>Add</b> and press “Sample label”: a photo is read and shown with the exact line it came from.</span></li>
              <li><span>Confirm it. <b>Today</b> flags clarithromycin with atorvastatin as a major interaction, with its source and path.</span></li>
              <li><span>Open <b>Graph</b> and click nodes: every one explains itself in plain words.</span></li>
              <li><span>In <b>Circle</b>, Meena has not seen the change. Move the time warp to +13 h and a reminder appears.</span></li>
            </ol>
          </section>
        </div>
      </div>
    </div>
  );
}
