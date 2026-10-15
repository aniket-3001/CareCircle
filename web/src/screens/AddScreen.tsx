import { useRef, useState } from 'react';
import { sampleLabel } from '../api/client';
import type { IntakeResult, Proposal } from '../api/types';
import { Pill, Spinner } from '../components/Pill';
import { useToast } from '../components/Toast';
import { title } from '../lib/format';
import { useApp } from '../state';

const KINDS: Record<string, 'photo' | 'voice' | 'document' | 'typed'> = { image: 'photo', voice: 'voice', document: 'document', typed: 'typed' };
const METHOD: Record<string, string> = { rapidocr: 'read with OCR', 'faster-whisper': 'heard with speech recognition', pypdf: 'text from a PDF', 'python-docx': 'text from a Word file', text: 'typed' };

export function AddScreen(): React.JSX.Element {
  const app = useApp();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const [text, setText] = useState('');
  const [recording, setRecording] = useState<MediaRecorder | null>(null);
  const [result, setResult] = useState<IntakeResult | null>(null);
  const [props, setProps] = useState<Proposal[]>([]);
  const file = useRef<HTMLInputElement>(null);

  async function run(body: FormData): Promise<void> {
    setBusy(true);
    try {
      const r = await app.api.intake(body);
      setResult(r);
      setProps(r.proposals);
      if (!r.proposals.length) toast(r.source.note ?? 'No medicine found in that. Try typing it.');
    } catch (e) {
      toast(`Could not read that: ${e instanceof Error ? e.message : 'unknown error'}`);
    } finally {
      setBusy(false);
    }
  }
  const send = (f: File) => {
    const fd = new FormData();
    fd.append('file', f);
    return run(fd);
  };

  async function toggleRecord(): Promise<void> {
    if (recording) { recording.stop(); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      rec.ondataavailable = (e) => chunks.push(e.data);
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        setRecording(null);
        void send(new File([new Blob(chunks)], 'note.webm', { type: 'audio/webm' }));
      };
      rec.start();
      setRecording(rec);
    } catch {
      toast('The microphone is not available here.');
    }
  }

  return (
    <div className="screen">
      <h1 className="headline">Add a medicine</h1>
      <section className="card" aria-labelledby="add-title">
        <h2 className="card__title" id="add-title">From a photo, voice note, document or text</h2>
        <label
          className={`drop${over ? ' drop--over' : ''}`}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f) void send(f); }}
        >
          <input ref={file} type="file" hidden accept="image/*,audio/*,.pdf,.docx,.txt" aria-label="Choose a photo, audio file or document" onChange={(e) => { const f = e.target.files?.[0]; if (f) void send(f); e.target.value = ''; }} />
          <b>Drop a file here or tap to choose</b>
          <span className="muted">Photo of a label · voice note · PDF · Word</span>
        </label>
        <div className="row row--wrap">
          <button type="button" className="button button--secondary button--small" disabled={busy} onClick={async () => send(await sampleLabel())}>
            Use a sample label
          </button>
          <button type="button" className={`button button--small ${recording ? 'button--danger' : 'button--secondary'}`} onClick={() => void toggleRecord()} aria-pressed={!!recording}>
            {recording ? 'Stop recording' : 'Record a voice note'}
          </button>
          {busy && <Spinner />}
        </div>
        <label className="field">
          Or type it
          <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. Clarithromycin 500 mg twice daily for 7 days" />
        </label>
        <div className="row">
          <button type="button" className="button" disabled={busy || !text.trim()} onClick={() => { const fd = new FormData(); fd.append('text', text); void run(fd); }}>
            Read it
          </button>
        </div>
        <p className="muted">Nothing is saved until you confirm each item, and every reading shows the exact line it came from.</p>
      </section>

      {result && (
        <>
          <section className="card">
            <div className="row row--wrap row--between">
              <h2 className="card__title">What was read</h2>
              <Pill tone="mute">{METHOD[result.source.method] ?? result.source.method}</Pill>
            </div>
            <pre className="quote" style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{result.text || result.source.note || 'Nothing readable.'}</pre>
          </section>
          {props.map((p, i) => (
            <ProposalCard
              key={`${p.quote}-${i}`}
              p={p}
              kind={KINDS[result.source.kind] ?? 'typed'}
              sourceText={result.text}
              onDone={() => setProps((cur) => cur.filter((_, j) => j !== i))}
            />
          ))}
        </>
      )}
    </div>
  );
}

function ProposalCard({ p, kind, sourceText, onDone }: { p: Proposal; kind: 'photo' | 'voice' | 'document' | 'typed'; sourceText: string; onDone: () => void }): React.JSX.Element {
  const app = useApp();
  const toast = useToast();
  const [drug, setDrug] = useState(p.drug_candidates[0]?.name ?? '');
  const [dose, setDose] = useState(p.dose_text);
  const [freq, setFreq] = useState(p.freq_text);
  const [busy, setBusy] = useState(false);

  async function confirm(): Promise<void> {
    setBusy(true);
    try {
      const r = await app.api.record({ drug, dose_text: dose, freq_text: freq, source_type: kind, quote: p.quote, source_text: sourceText || p.quote });
      await app.api.confirm(r.id);
      toast(`Saved ${title(drug)}. The other carers will be asked to acknowledge it.`);
      app.bump();
      onDone();
      app.go('today');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not save');
      setBusy(false);
    }
  }

  return (
    <section className="card" data-testid="proposal">
      <div className="row row--wrap">
        {p.verified ? <Pill tone="ok">quote verified</Pill> : <Pill tone="warn">quote not found in source</Pill>}
        <Pill>{p.method === 'bedrock' ? 'model-assisted' : 'rules'}</Pill>
      </div>
      <blockquote className="quote">“{p.quote}”</blockquote>
      <div className="grid-2">
        <label className="field">
          Medicine (pick the right one)
          <select value={drug} onChange={(e) => setDrug(e.target.value)}>
            {p.drug_candidates.map((c) => <option key={c.name} value={c.name}>{title(c.name)}</option>)}
          </select>
        </label>
        <label className="field">
          For
          <input type="text" value={app.session.person} readOnly aria-readonly="true" />
        </label>
        <label className="field">
          Dose as written
          <input type="text" value={dose} onChange={(e) => setDose(e.target.value)} />
        </label>
        <label className="field">
          How often as written
          <input type="text" value={freq} onChange={(e) => setFreq(e.target.value)} />
        </label>
      </div>
      <div className="row">
        <button type="button" className="button" disabled={busy || !drug} onClick={() => void confirm()}>Confirm and save</button>
        <button type="button" className="button button--secondary" onClick={onDone}>Discard</button>
        {busy && <Spinner />}
      </div>
    </section>
  );
}
