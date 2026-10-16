import { Ban, Pencil } from 'lucide-react';
import { useState } from 'react';
import type { RegimenEntry } from '../api/types';
import { title } from '../lib/format';
import { useApp } from '../state';
import { Sheet } from './Sheet';
import { useToast } from './Toast';
import { tr } from '../lib/i18n';

/** Change what is on record for a medicine, or record that it was stopped. Both add a NEW entry that closes the old one (nothing is overwritten, and the
 *  history keeps both). They record what a carer was told: they never tell anyone to change or stop anything. */
export function MedActions({ r }: { r: RegimenEntry }): React.JSX.Element {
  const app = useApp();
  const toast = useToast();
  const [mode, setMode] = useState<'edit' | 'stop' | null>(null);
  const [dose, setDose] = useState(r.dose_text);
  const [freq, setFreq] = useState(r.freq_text);
  const [busy, setBusy] = useState(false);

  async function save(action: 'set' | 'stop'): Promise<void> {
    setBusy(true);
    try {
      const rec = await app.api.record({ drug: r.drug, action, dose_text: action === 'stop' ? r.dose_text : dose, freq_text: action === 'stop' ? r.freq_text : freq, source_type: 'typed', quote: '', source_text: '', product: r.product ?? '' });
      await app.api.confirm(rec.id);
      toast(rec.warning ? `${title(r.drug)} updated. ${rec.warning}` : action === 'stop' ? `${title(r.drug)} recorded as stopped. The other carers will be asked to acknowledge it.` : `${title(r.drug)} updated. The other carers will be asked to acknowledge it.`);
      setMode(null);
      app.bump();
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not save');
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="row">
        <button type="button" className="icon-btn" aria-label={`Change the recorded dose of ${title(r.drug)}`} onClick={() => { setDose(r.dose_text); setFreq(r.freq_text); setMode('edit'); }}><Pencil size={16} aria-hidden="true" /></button>
        <button type="button" className="icon-btn" aria-label={`Record ${title(r.drug)} as stopped`} onClick={() => setMode('stop')}><Ban size={16} aria-hidden="true" /></button>
      </div>
      <Sheet open={mode === 'edit'} title={`Change ${title(r.drug)}`} onClose={() => setMode(null)}>
        <p className="muted">{tr('Record what the prescriber or the label now says. The old entry stays in the history.')}</p>
        <label className="field">{tr('Dose as written')}<input type="text" value={dose} onChange={(e) => setDose(e.target.value)} /></label>
        <label className="field">{tr('How often as written')}<input type="text" value={freq} onChange={(e) => setFreq(e.target.value)} /></label>
        <button type="button" className="btn" disabled={busy || (dose === r.dose_text && freq === r.freq_text)} onClick={() => void save('set')}>{tr('Save change')}</button>
      </Sheet>
      <Sheet open={mode === 'stop'} title={`Record ${title(r.drug)} as stopped?`} onClose={() => setMode(null)}>
        <p>This records that {title(r.drug)} was stopped, for example by the prescriber. It does not tell anyone to stop anything. It leaves the current list and the checks, and stays in the history.</p>
        <button type="button" className="btn btn--danger" disabled={busy} onClick={() => void save('stop')}>{tr('Record as stopped')}</button>
      </Sheet>
    </>
  );
}
