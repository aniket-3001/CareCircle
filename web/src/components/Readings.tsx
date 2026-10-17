import { Activity, LineChart, Trash2 } from 'lucide-react';
import { useState } from 'react';
import type { Reading, Trend } from '../api/types';
import { Async } from './Async';
import { Pill, Spinner } from './Pill';
import { Sheet } from './Sheet';
import { useToast } from './Toast';
import { ago, nameOf, plural, title } from '../lib/format';
import { useApp, useLoad } from '../state';
import { tr } from '../lib/i18n';

const KINDS: Record<string, { label: string; units: string[] }> = {
  bp_systolic: { label: 'Blood pressure, top number', units: ['mmHg'] },
  bp_diastolic: { label: 'Blood pressure, bottom number', units: ['mmHg'] },
  heart_rate: { label: 'Pulse', units: ['bpm'] },
  glucose: { label: 'Blood sugar', units: ['mg/dL', 'mmol/L'] },
  inr: { label: 'INR', units: ['ratio'] },
  weight: { label: 'Weight', units: ['kg', 'lb'] },
  temperature: { label: 'Temperature', units: ['C', 'F'] },
  spo2: { label: 'Oxygen saturation', units: ['%'] },
  tsh: { label: 'Thyroid (TSH)', units: ['mIU/L'] },
};

/** A line of readings with the dates a medicine's entry changed marked on it. Nothing here says whether a number is good or bad. */
function Chart({ t }: { t: Trend }): React.JSX.Element {
  const W = 560, H = 220, P = 34;
  const pts = t.series;
  if (pts.length < 2) return <p className="muted">{tr('Add at least two readings to see a line.')}</p>;
  const xs = pts.map((r) => r.at), ys = pts.map((r) => r.value);
  const x0 = Math.min(...xs, ...t.changes.map((c) => c.at)), x1 = Math.max(...xs);
  const y0 = Math.min(...ys), y1 = Math.max(...ys);
  const X = (v: number) => P + ((v - x0) / Math.max(1, x1 - x0)) * (W - 2 * P);
  const Y = (v: number) => H - P - ((v - y0) / Math.max(1e-9, y1 - y0 || 1)) * (H - 2 * P);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${t.label} over time with medicine changes marked`} style={{ width: '100%', height: 'auto' }}>
      <line x1={P} y1={H - P} x2={W - P} y2={H - P} stroke="var(--line)" />
      <text x={P} y={H - 10} fontSize="11" fill="var(--muted)">{new Date(x0).toLocaleDateString()}</text>
      <text x={W - P} y={H - 10} fontSize="11" fill="var(--muted)" textAnchor="end">{new Date(x1).toLocaleDateString()}</text>
      <text x={6} y={Y(y1) + 4} fontSize="11" fill="var(--muted)">{y1}</text>
      <text x={6} y={Y(y0) + 4} fontSize="11" fill="var(--muted)">{y0}</text>
      {t.changes.map((c) => (
        <g key={c.dose}>
          <line x1={X(c.at)} y1={P / 2} x2={X(c.at)} y2={H - P} stroke="#d77a61" strokeDasharray="4 4" />
          <text x={X(c.at) + 3} y={P / 2 + 8} fontSize="10" fill="var(--danger)">{c.action === 'stop' ? 'stopped' : c.text.slice(0, 18)}</text>
        </g>
      ))}
      <polyline fill="none" stroke="var(--ink)" strokeWidth="2" points={pts.map((r) => `${X(r.at)},${Y(r.value)}`).join(' ')} />
      {pts.map((r) => <circle key={r.id} cx={X(r.at)} cy={Y(r.value)} r="3.5" fill="var(--ink)"><title>{`${r.value} ${r.unit}, ${new Date(r.at).toLocaleString()}`}</title></circle>)}
    </svg>
  );
}

export function Readings(): React.JSX.Element {
  const app = useApp();
  const toast = useToast();
  const list = useLoad((a) => a.api.measures(), [app.rev]);
  const reg = useLoad((a) => a.api.regimen(), [app.rev]);
  const [kind, setKind] = useState('bp_systolic');
  const [unit, setUnit] = useState('mmHg');
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<{ kind: string; drug: string } | null>(null);
  const [trend, setTrend] = useState<Trend | null>(null);

  async function add(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    setBusy(true);
    try {
      await app.api.measure(kind, Number(value), unit);
      setValue('');
      toast('Reading saved');
      app.bump();
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Could not save the reading');
    } finally {
      setBusy(false);
    }
  }
  async function open(k: string, drug = ''): Promise<void> {
    setView({ kind: k, drug });
    setTrend(null);
    try { setTrend(await app.api.trend(k, drug, app.now())); } catch (err) { toast(err instanceof Error ? err.message : 'Could not load'); setView(null); }
  }
  const kindsWith = (rows: Reading[]) => [...new Set(rows.map((r) => r.kind))];

  return (
    <section className="card" aria-labelledby="read-title" data-testid="readings">
      <div className="card-head"><h2 id="read-title">{tr('Readings')}</h2><Activity size={20} aria-hidden="true" /></div>
      <p className="muted small">{tr('Blood pressure, sugar, INR and so on, kept next to the medicine changes. The app draws what was typed and never says whether a number is good or bad.')}</p>
      <form className="grid-2" onSubmit={add}>
        <label className="field">{tr('What')}
          <select value={kind} onChange={(e) => { setKind(e.target.value); setUnit(KINDS[e.target.value].units[0]); }}>
            {Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
        </label>
        <label className="field">{tr('Reading')}
          <span className="row">
            <input type="number" step="any" inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} required />
            {KINDS[kind].units.length > 1
              ? <select aria-label={tr('Unit')} value={unit} onChange={(e) => setUnit(e.target.value)}>{KINDS[kind].units.map((u) => <option key={u}>{u}</option>)}</select>
              : <span className="muted">{unit}</span>}
          </span>
        </label>
        <div className="row"><button type="submit" className="btn btn--sm" disabled={busy || value === ''}>{tr('Save reading')}</button>{busy && <Spinner />}</div>
      </form>
      <Async state={list}>
        {(rows) => rows.length === 0 ? <p className="muted">{tr('No readings yet.')}</p> : (
          <>
            <div className="chips" aria-label={tr('Charts')}>
              {kindsWith(rows).map((k) => <button key={k} type="button" className="fchip" onClick={() => void open(k)}><LineChart size={14} aria-hidden="true" /> {KINDS[k]?.label ?? k}</button>)}
            </div>
            <div className="rows">
              {rows.slice(0, 5).map((r) => (
                <div key={r.id} className="item">
                  <div><div className="item__title">{r.label} <span className="muted">{r.value} {r.unit}</span></div><div className="item__sub">{nameOf(r.by)}, {ago(r.at, app.now())}</div></div>
                  <button type="button" className="icon-btn" aria-label={`Remove this ${r.label} reading`} onClick={() => void app.api.forgetMeasure(r.id).then(() => { toast('Reading removed'); app.bump(); })}><Trash2 size={16} aria-hidden="true" /></button>
                </div>
              ))}
            </div>
          </>
        )}
      </Async>
      <Sheet open={!!view} title={view ? (KINDS[view.kind]?.label ?? view.kind) : ''} onClose={() => setView(null)}>
        {!trend ? <Spinner /> : (
          <div className="stack">
            <label className="field">{tr('Mark the changes of')}
              <select value={view?.drug ?? ''} onChange={(e) => void open(view!.kind, e.target.value)}>
                <option value="">no medicine</option>
                {(reg.data ?? []).map((r) => <option key={r.id} value={r.drug}>{title(r.drug)}</option>)}
              </select>
            </label>
            <Chart t={trend} />
            {trend.changes.length > 0 && (
              <div className="rows">
                {trend.changes.map((c) => (
                  <div key={c.dose} className="item">
                    <div>
                      <div className="item__title">{c.action === 'stop' ? 'Stopped' : c.text} <Pill tone="mute">{new Date(c.at).toLocaleDateString()}</Pill></div>
                      <div className="item__sub">{plural(trend.window_days, 'day')} before: {plural(c.before.n, 'reading')}{c.before.mean !== null ? `, mean ${c.before.mean}` : ''}. After: {plural(c.after.n, 'reading')}{c.after.mean !== null ? `, mean ${c.after.mean}` : ''}.</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <p className="muted small">{trend.note}</p>
          </div>
        )}
      </Sheet>
    </section>
  );
}
