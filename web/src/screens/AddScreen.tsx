import { Camera, FileText, Mic, ScanLine, Square } from 'lucide-react';
import { motion } from 'motion/react';
import { useRef, useState } from 'react';
import { sampleLabel } from '../api/client';
import type { IntakeResult, Proposal } from '../api/types';
import { PageHead } from '../components/PageHead';
import { Pill, Spinner } from '../components/Pill';
import { useToast } from '../components/Toast';
import { title } from '../lib/format';
import { useApp } from '../state';
import { tr } from '../lib/i18n';

const KINDS: Record<string, 'photo' | 'voice' | 'document' | 'typed'> = { image: 'photo', voice: 'voice', document: 'document', typed: 'typed' };
const METHOD: Record<string, string> = { rapidocr: 'read with OCR', 'faster-whisper': 'heard with speech recognition', pypdf: 'text from a PDF', 'python-docx': 'text from a Word file', text: 'typed' };

export function AddScreen(): React.JSX.Element {
  const app = useApp();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState<string | null>(null);
  const [text, setText] = useState('');
  const [recording, setRecording] = useState<MediaRecorder | null>(null);
  const [result, setResult] = useState<IntakeResult | null>(null);
  const [props, setProps] = useState<Proposal[]>([]);
  const photo = useRef<HTMLInputElement>(null);
  const doc = useRef<HTMLInputElement>(null);

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
  const drop = (kind: string) => ({
    onDragOver: (e: React.DragEvent) => { e.preventDefault(); setOver(kind); },
    onDragLeave: () => setOver(null),
    onDrop: (e: React.DragEvent) => { e.preventDefault(); setOver(null); const f = e.dataTransfer.files[0]; if (f) void send(f); },
  });

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

  const pick = (ref: React.RefObject<HTMLInputElement>, accept: string, label: string) => (
    <input ref={ref} type="file" hidden accept={accept} aria-label={label} onChange={(e) => { const f = e.target.files?.[0]; if (f) void send(f); e.target.value = ''; }} />
  );

  return (
    <div className="screen">
      <PageHead crumb={tr('Add to the record')} title={tr('Add a medicine')} lede={tr('From a photo, a voice note, a document or text. Nothing is saved until you confirm, and every reading shows the exact line it came from.')} />
      <div className="layout">
        <div className="col">
          <section className="card" aria-labelledby="add-title">
            <div className="card-head">
              <h2 id="add-title">{tr('Choose how')}</h2>
              {busy && <Spinner />}
            </div>
            <div className="tiles">
              <button type="button" className={`tile${over === 'photo' ? ' tile--over' : ''}`} onClick={() => photo.current?.click()} {...drop('photo')}>
                <span className="ico"><Camera size={26} strokeWidth={1.75} aria-hidden="true" /></span>
                <b>{tr('Photo')}</b>
                <span>of a label or box</span>
              </button>
              {pick(photo, 'image/*', 'Choose a photo of a label')}
              <button type="button" className={`tile${recording ? ' tile--rec' : ''}`} onClick={() => void toggleRecord()} aria-pressed={!!recording} aria-label={recording ? 'Stop recording' : 'Record a voice note'}>
                <span className="ico">{recording ? <Square size={22} strokeWidth={1.75} aria-hidden="true" /> : <Mic size={26} strokeWidth={1.75} aria-hidden="true" />}</span>
                <b>{recording ? 'Stop' : 'Voice note'}</b>
                <span>{recording ? 'Recording…' : 'say it out loud'}</span>
              </button>
              <button type="button" className={`tile${over === 'doc' ? ' tile--over' : ''}`} onClick={() => doc.current?.click()} {...drop('doc')}>
                <span className="ico"><FileText size={26} strokeWidth={1.75} aria-hidden="true" /></span>
                <b>{tr('Document')}</b>
                <span>{tr('PDF or Word')}</span>
              </button>
              {pick(doc, 'audio/*,.pdf,.docx,.txt', 'Choose a document or audio file')}
              <button type="button" className="tile" disabled={busy} onClick={async () => send(await sampleLabel())}>
                <span className="ico"><ScanLine size={26} strokeWidth={1.75} aria-hidden="true" /></span>
                <b>{tr('Sample label')}</b>
                <span>try it without a photo</span>
              </button>
            </div>
          </section>
          <section className="card" aria-labelledby="type-title">
            <h2 id="type-title">{tr('Or type it')}</h2>
            <label className="field">
              <span className="sr-only">{tr('Medicine, dose and how often')}</span>
              <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. Clarithromycin 500 mg twice daily for 7 days" />
            </label>
            <div className="row">
              <button type="button" className="btn" disabled={busy || !text.trim()} onClick={() => { const fd = new FormData(); fd.append('text', text); void run(fd); }}>
                {tr('Read it')}
              </button>
            </div>
          </section>
        </div>
        <div className="col">
          {result && (
            <section className="card">
              <div className="card-head">
                <h2>{tr('What was read')}</h2>
                <Pill tone="mute">{METHOD[result.source.method] ?? result.source.method}</Pill>
              </div>
              <pre className="quote" style={{ whiteSpace: 'pre-wrap', margin: 0, font: 'inherit' }}>{result.text || result.source.note || 'Nothing readable.'}</pre>
            </section>
          )}
          {props.map((p, i) => (
            <motion.div key={`${p.drug_candidates[0]?.name ?? ''}|${p.quote}`} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
              <ProposalCard p={p} kind={KINDS[result?.source.kind ?? 'typed'] ?? 'typed'} sourceText={result?.text ?? ''} sourceId={result?.source_id ?? ''} goToday={props.length <= 1} onDone={() => setProps((cur) => cur.filter((_, j) => j !== i))} />
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function ProposalCard({ p, kind, sourceText, sourceId = '', goToday = true, onDone }: { p: Proposal; kind: 'photo' | 'voice' | 'document' | 'typed'; sourceText: string; sourceId?: string; goToday?: boolean; onDone: () => void }): React.JSX.Element {
  const app = useApp();
  const toast = useToast();
  const [pick, setPick] = useState(p.drug_candidates[0]?.name ?? '');
  const [typed, setTyped] = useState('');
  const OTHER = '__other__';
  const drug = pick === OTHER ? typed.trim().toLowerCase() : pick;
  const picked = p.drug_candidates.find((c) => c.name === pick);
  const unchecked = pick === OTHER || !!picked?.unchecked;
  const [dose, setDose] = useState(p.dose_text);
  const [freq, setFreq] = useState(p.freq_text);
  const [busy, setBusy] = useState(false);

  async function confirm(): Promise<void> {
    setBusy(true);
    try {
      const edited = [drug !== (p.drug_candidates[0]?.name ?? '') && 'drug', dose !== p.dose_text && 'dose', freq !== p.freq_text && 'freq'].filter(Boolean).join(',');
      const r = await app.api.record({ edited, drug, dose_text: dose, freq_text: freq, source_type: kind, quote: p.quote, source_text: sourceText || p.quote, source_ref: sourceId });
      await app.api.confirm(r.id);
      toast(`Saved ${title(drug)}. ${r.warning ? `${r.warning} ` : ''}The other carers will be asked to acknowledge it.`);
      app.bump();
      onDone();
      if (goToday) app.go('today');                      // with more proposals waiting (the ingredients of a combination), stay and confirm the rest
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not save');
      setBusy(false);
    }
  }

  return (
    <section className="card" data-testid="proposal">
      <div className="row row--wrap">
        {p.verified ? <Pill tone="ok">quote verified</Pill> : <Pill tone="warn">quote not found in source</Pill>}
        <Pill>{p.method === 'bedrock' ? 'model-assisted' : p.method === 'brand list' ? 'brand list' : 'rules'}</Pill>
      </div>
      {p.combination && (
        <p className="muted small" data-testid="combination-note">
          {tr('This is a combination product.')} <b>{p.combination}</b> {tr('usually contains')} {(p.combination_ingredients ?? []).map(title).join(' + ')}
          {p.combination_strength ? ` (${tr('printed strength')}: ${p.combination_strength})` : ''}. {tr('Each ingredient is saved on its own, so confirm each one. From a hand-written list: check the pack.')}
        </p>
      )}
      <blockquote className="quote">“{p.quote}”</blockquote>
      <div className="grid-2">
        <label className="field">
          {tr('Medicine (pick the right one)')}
          <select value={pick} onChange={(e) => setPick(e.target.value)}>
            {p.drug_candidates.map((c) => <option key={c.name} value={c.name}>{title(c.name)}{c.unchecked ? ` (${tr('not checked')})` : ''}</option>)}
            <option value={OTHER}>{tr('Another medicine: type its name')}</option>
          </select>
        </label>
        {pick === OTHER && (
          <label className="field">
            {tr('Medicine name')}
            <input type="text" value={typed} maxLength={80} onChange={(e) => setTyped(e.target.value)} data-testid="other-drug" />
          </label>
        )}
        <label className="field">
          {tr('For')}
          <input type="text" value={app.session.person} readOnly aria-readonly="true" />
        </label>
        <label className="field">
          {tr('Dose as written')}
          <input type="text" value={dose} onChange={(e) => setDose(e.target.value)} />
        </label>
        <label className="field">
          {tr('How often as written')}
          <input type="text" value={freq} onChange={(e) => setFreq(e.target.value)} />
        </label>
      </div>
      {unchecked && <p className="muted small" data-testid="unchecked-note">{tr('If this medicine is not in our reference data it is recorded, but nothing is checked for it, and the verdict says so.')}</p>}
      <div className="row">
        <button type="button" className="btn" disabled={busy || !drug} onClick={() => void confirm()}>{tr('Confirm and save')}</button>
        <button type="button" className="btn btn--soft" onClick={onDone}>{tr('Discard')}</button>
        {busy && <Spinner />}
      </div>
    </section>
  );
}
