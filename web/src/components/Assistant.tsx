import { Mic, SendHorizontal, Sparkles, Square, Trash2, Volume2, VolumeX } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ChatMessage } from '../api/types';
import { ProposalCard } from '../screens/AddScreen';
import { useApp, type TabId } from '../state';
import { Pill, Spinner } from './Pill';
import { Sheet } from './Sheet';
import { useToast } from './Toast';

const SUGGESTIONS = ['Who has not seen the latest change?', 'What is on record?', 'What does the record flag?', 'What changed recently?'];
const BASIS: Record<string, { text: string; tone: 'ok' | 'info' | 'warn' | 'mute' }> = {
  rules: { text: 'from the record', tone: 'ok' },
  model: { text: 'AI-assisted, from the record', tone: 'info' },
  refusal: { text: 'not advice', tone: 'warn' },
  proposal: { text: 'needs your confirmation', tone: 'info' },
};

const voiceOn = (): boolean => { try { return window.localStorage.getItem('cc-voice') === 'on'; } catch { return false; } };

/** The helper. It answers from the circle's own record (the server decides what it may say), prepares entries for you to confirm, and refuses to advise.
 *  The conversation is stored on the server for this carer, so it is the same on every device. */
export function Assistant({ open, onClose, initial }: { open: boolean; onClose: () => void; initial?: string }): React.JSX.Element {
  const app = useApp();
  const toast = useToast();
  const [msgs, setMsgs] = useState<ChatMessage[] | null>(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [rec, setRec] = useState<MediaRecorder | null>(null);
  const [speak, setSpeak] = useState(voiceOn);
  const [left, setLeft] = useState<number | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const sent = useRef('');

  useEffect(() => { if (open) app.api.chat().then(setMsgs, () => setMsgs([])); }, [open, app.api, app.rev]);
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }); }, [msgs, busy]);

  const say = useCallback(async (text: string) => {
    const q = text.trim();
    if (!q || busy) return;
    setBusy(true);
    setDraft('');
    setMsgs((cur) => [...(cur ?? []), { id: `tmp-${Date.now()}`, role: 'user', text: q, at: Date.now(), source: '', links: [], proposals: [] }]);
    try {
      const a = await app.api.ask(q);
      setLeft(a.left_today ?? null);
      setMsgs((cur) => [...(cur ?? []), a]);
      if (speak && 'speechSynthesis' in window) window.speechSynthesis.speak(new SpeechSynthesisUtterance(a.text));
    } catch (e) {
      toast(e instanceof Error ? e.message : 'The assistant could not answer');
    } finally {
      setBusy(false);
    }
  }, [app.api, busy, speak, toast]);

  useEffect(() => {
    if (open && initial && initial !== sent.current && msgs !== null) { sent.current = initial; void say(initial); }
    if (!open) sent.current = '';
  }, [open, initial, msgs, say]);

  async function mic(): Promise<void> {
    if (rec) { rec.stop(); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const r = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      r.ondataavailable = (e) => chunks.push(e.data);
      r.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setRec(null);
        setBusy(true);
        try {
          const fd = new FormData();
          fd.append('file', new File([new Blob(chunks)], 'q.webm', { type: 'audio/webm' }));
          const t = await app.api.intake(fd);
          setBusy(false);
          if (t.text) void say(t.text); else toast('I could not hear anything in that.');
        } catch { setBusy(false); toast('Could not transcribe that.'); }
      };
      r.start();
      setRec(r);
    } catch {
      toast('The microphone is not available here.');
    }
  }

  const toggleSpeak = () => { const v = !speak; setSpeak(v); try { window.localStorage.setItem('cc-voice', v ? 'on' : 'off'); } catch { /* convenience only */ } if (!v) window.speechSynthesis?.cancel(); };

  return (
    <Sheet open={open} title="Ask the helper" onClose={onClose}>
      <div className="chat" data-testid="assistant">
        <p className="muted small">I answer from this circle's record, prepare entries for you to confirm, and never give medical advice. Your conversation is saved to your account.</p>
        <div className="chat-log" role="log" aria-live="polite">
          {msgs === null && <Spinner />}
          {msgs?.length === 0 && (
            <div className="chips" aria-label="Suggestions">
              {SUGGESTIONS.map((s) => <button key={s} type="button" className="fchip" onClick={() => void say(s)}>{s}</button>)}
            </div>
          )}
          {msgs?.map((m) => (
            <div key={m.id} className={`bubble bubble--${m.role}`} data-testid={`msg-${m.role}`}>
              <div>{m.text}</div>
              {m.role === 'assistant' && m.source && <div className="row row--wrap" style={{ marginTop: 6 }}><Pill tone={BASIS[m.source]?.tone ?? 'mute'}>{BASIS[m.source]?.text ?? m.source}</Pill>{m.links.map((l) => <button key={l.tab} type="button" className="btn btn--ghost btn--sm" onClick={() => { app.go(l.tab as TabId); onClose(); }}>{l.label}</button>)}</div>}
              {m.proposals.length > 0 && m.proposals.slice(0, 1).map((p, i) => (
                <div key={i} style={{ marginTop: 10 }}><ProposalCard p={p} kind="typed" sourceText={m.proposal_text ?? p.quote} onDone={() => setMsgs((cur) => (cur ?? []).map((x) => (x.id === m.id ? { ...x, proposals: [] } : x)))} /></div>
              ))}
            </div>
          ))}
          {busy && <div className="bubble bubble--assistant"><Spinner /></div>}
          <div ref={end} />
        </div>
        <form className="chat-input" onSubmit={(e) => { e.preventDefault(); void say(draft); }}>
          <label className="sr-only" htmlFor="ask">Your question</label>
          <input id="ask" type="text" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Ask about the record…" maxLength={300} autoComplete="off" />
          <button type="button" className={`icon-btn${rec ? ' icon-btn--rec' : ''}`} onClick={() => void mic()} aria-label={rec ? 'Stop recording' : 'Ask by voice'}>{rec ? <Square size={18} aria-hidden="true" /> : <Mic size={18} aria-hidden="true" />}</button>
          <button type="submit" className="btn btn--sm" disabled={busy || !draft.trim()} aria-label="Send"><SendHorizontal size={18} aria-hidden="true" /></button>
        </form>
        <div className="row row--between">
          <button type="button" className="btn btn--ghost btn--sm" onClick={toggleSpeak} aria-pressed={speak}>{speak ? <Volume2 size={16} aria-hidden="true" /> : <VolumeX size={16} aria-hidden="true" />} {speak ? 'Reading answers aloud' : 'Read answers aloud'}</button>
          <div className="row">
            {left !== null && <span className="muted small">{left} left today</span>}
            {!!msgs?.length && <button type="button" className="btn btn--ghost btn--sm" onClick={() => void app.api.clearChat().then(() => { setMsgs([]); toast('Conversation deleted'); })}><Trash2 size={16} aria-hidden="true" /> Clear</button>}
          </div>
        </div>
      </div>
    </Sheet>
  );
}

export const AssistantIcon = Sparkles;
