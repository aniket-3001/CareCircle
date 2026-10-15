import { Mic, SendHorizontal, Sparkles, Square, Trash2, Volume2, VolumeX } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ChatMessage } from '../api/types';
import { ProposalCard } from '../screens/AddScreen';
import { getLang, useT } from '../lib/i18n';
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

/** One utterance in the language of the text: Hindi (hi-IN, with a Hindi voice when the device has one) or English. */
function utter(text: string): SpeechSynthesisUtterance {
  const u = new SpeechSynthesisUtterance(text);
  if (/[ऀ-ॿ]/.test(text) || getLang() === 'hi') {
    u.lang = 'hi-IN';
    const v = window.speechSynthesis.getVoices().find((x) => x.lang.toLowerCase().startsWith('hi'));
    if (v) u.voice = v;
  }
  return u;
}

interface SpeechRec {
  continuous: boolean; interimResults: boolean; lang: string;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null; onerror: (() => void) | null;
  start: () => void; stop: () => void;
}

const voiceOn = (): boolean => { try { return window.localStorage.getItem('cc-voice') === 'on'; } catch { return false; } };

/** The helper. It answers from the circle's own record (the server decides what it may say), prepares entries for you to confirm, and refuses to advise.
 *  The conversation is stored on the server for this carer, so it is the same on every device. */
export function Assistant({ open, onClose, initial }: { open: boolean; onClose: () => void; initial?: string }): React.JSX.Element {
  const app = useApp();
  const t = useT();
  const toast = useToast();
  const [msgs, setMsgs] = useState<ChatMessage[] | null>(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [rec, setRec] = useState<MediaRecorder | null>(null);
  const [speak, setSpeak] = useState(voiceOn);
  const [left, setLeft] = useState<number | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const live = useRef('');
  const recog = useRef<{ stop: () => void } | null>(null);
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
      const a = await app.api.ask(q, getLang());
      setLeft(a.left_today ?? null);
      setMsgs((cur) => [...(cur ?? []), a]);
      if (speak && 'speechSynthesis' in window) window.speechSynthesis.speak(utter(a.text));
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
      // live captions while speaking (the browser's own recogniser, where it has one); the recording is the fallback
      live.current = '';
      const SR = (window as unknown as { SpeechRecognition?: new () => SpeechRec; webkitSpeechRecognition?: new () => SpeechRec }).SpeechRecognition
        ?? (window as unknown as { webkitSpeechRecognition?: new () => SpeechRec }).webkitSpeechRecognition;
      if (SR) {
        const sr = new SR();
        sr.continuous = true;
        sr.interimResults = true;
        sr.lang = getLang() === 'hi' ? 'hi-IN' : 'en-IN';
        sr.onresult = (e) => {
          let text = '';
          for (let i = 0; i < e.results.length; i++) text += e.results[i][0].transcript + ' ';
          live.current = text.trim();
          setDraft(live.current);
        };
        sr.onerror = () => undefined;
        try { sr.start(); recog.current = sr; } catch { recog.current = null; }
      }
      r.ondataavailable = (e) => chunks.push(e.data);
      r.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        recog.current?.stop();
        recog.current = null;
        setRec(null);
        if (live.current) { const said = live.current; live.current = ''; void say(said); return; }
        setBusy(true);
        try {
          const fd = new FormData();
          fd.append('file', new File([new Blob(chunks)], 'q.webm', { type: 'audio/webm' }));
          if (getLang() === 'hi') fd.append('language', 'hi');
          const heard = await app.api.intake(fd);
          setBusy(false);
          if (heard.text) void say(heard.text); else toast(t('I could not hear anything in that.'));
        } catch { setBusy(false); toast(t('Could not transcribe that.')); }
      };
      r.start();
      setRec(r);
    } catch {
      toast('The microphone is not available here.');
    }
  }

  const toggleSpeak = () => { const v = !speak; setSpeak(v); try { window.localStorage.setItem('cc-voice', v ? 'on' : 'off'); } catch { /* convenience only */ } if (!v) window.speechSynthesis?.cancel(); };

  return (
    <Sheet open={open} title={t('Ask the helper')} onClose={onClose}>
      <div className="chat" data-testid="assistant">
        <p className="muted small">I answer from this circle's record, prepare entries for you to confirm, and never give medical advice. Your conversation is saved to your account.</p>
        <div className="chat-log" role="log" aria-live="polite">
          {msgs === null && <Spinner />}
          {msgs?.length === 0 && (
            <div className="chips" aria-label="Suggestions">
              {SUGGESTIONS.map((s) => <button key={s} type="button" className="fchip" onClick={() => void say(t(s))}>{t(s)}</button>)}
            </div>
          )}
          {msgs?.map((m) => (
            <div key={m.id} className={`bubble bubble--${m.role}`} data-testid={`msg-${m.role}`}>
              <div>{m.text}</div>
              {m.role === 'assistant' && m.source && <div className="row row--wrap" style={{ marginTop: 6 }}><Pill tone={BASIS[m.source]?.tone ?? 'mute'}>{t(BASIS[m.source]?.text ?? m.source)}</Pill>{m.links.map((l) => <button key={l.tab} type="button" className="btn btn--ghost btn--sm" onClick={() => { app.go(l.tab as TabId); onClose(); }}>{l.label}</button>)}</div>}
              {m.proposals.length > 0 && m.proposals.slice(0, 1).map((p, i) => (
                <div key={i} style={{ marginTop: 10 }}><ProposalCard p={p} kind="typed" sourceText={m.proposal_text ?? p.quote} onDone={() => setMsgs((cur) => (cur ?? []).map((x) => (x.id === m.id ? { ...x, proposals: [] } : x)))} /></div>
              ))}
            </div>
          ))}
          {busy && <div className="bubble bubble--assistant"><Spinner /></div>}
          <div ref={end} />
        </div>
        <form className="chat-input" onSubmit={(e) => { e.preventDefault(); void say(draft); }}>
          <label className="sr-only" htmlFor="ask">{t('Your question')}</label>
          <input id="ask" type="text" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={t('Ask about the record…')} maxLength={300} autoComplete="off" />
          <button type="button" className={`icon-btn${rec ? ' icon-btn--rec' : ''}`} onClick={() => void mic()} aria-label={t(rec ? 'Stop recording' : 'Ask by voice')}>{rec ? <Square size={18} aria-hidden="true" /> : <Mic size={18} aria-hidden="true" />}</button>
          <button type="submit" className="btn btn--sm" disabled={busy || !draft.trim()} aria-label={t('Send')}><SendHorizontal size={18} aria-hidden="true" /></button>
        </form>
        <div className="row row--between">
          <button type="button" className="btn btn--ghost btn--sm" onClick={toggleSpeak} aria-pressed={speak}>{speak ? <Volume2 size={16} aria-hidden="true" /> : <VolumeX size={16} aria-hidden="true" />} {t(speak ? 'Reading answers aloud' : 'Read answers aloud')}</button>
          <div className="row">
            {left !== null && <span className="muted small">{left} {t('left today')}</span>}
            {!!msgs?.length && <button type="button" className="btn btn--ghost btn--sm" onClick={() => void app.api.clearChat().then(() => { setMsgs([]); toast(t('Conversation deleted')); })}><Trash2 size={16} aria-hidden="true" /> {t('Clear')}</button>}
          </div>
        </div>
      </div>
    </Sheet>
  );
}

export const AssistantIcon = Sparkles;
