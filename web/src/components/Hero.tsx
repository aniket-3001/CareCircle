import type { LucideIcon } from 'lucide-react';
import type { CheckResult } from '../api/types';
import { SEVERITY, levelVars, sevKey, worstSeverity } from '../design/levels';
import { pct, title } from '../lib/format';
import { useSettle } from '../lib/useSettle';
import { FaceIcon } from './Face';

const HEAD: Record<string, string> = {
  major: 'Major interaction flagged',
  moderate: 'Interactions flagged',
  minor: 'Minor flags only',
  unrated: 'Not enough to judge',
  none: 'No known conflict',
};

export interface Chip {
  Icon: LucideIcon;
  text: string;
}

/** The status card: how many things the record flags, what that means, the most serious one, and the circle at a glance.
 *  It never says "safe": with nothing flagged it says what the data does and does not cover. */
export function Hero({ check, chips }: { check: CheckResult; chips: Chip[] }): React.JSX.Element {
  const j = check.judgement;
  const n = check.direct.length + check.enzyme_paths.length;
  const shown = useSettle(n);
  const noData = j.state === 'no_data';
  const sev = worstSeverity(check);
  const level = SEVERITY[sev];
  const top = [...check.direct].sort((a, b) => (sevKey(b.level) === 'major' ? 1 : 0) - (sevKey(a.level) === 'major' ? 1 : 0))[0];
  const risk = check.regimen_risk;
  return (
    <section className={`hero${noData ? ' hero--neutral' : ''}`} style={noData ? undefined : levelVars(sev)} aria-labelledby="hero-title" data-testid="verdict" data-state={j.state}>
      <div className="hero-top">
        <div className="badge">
          <span className="sr-only">{n} flags</span>
          <span className="badge-num" aria-hidden="true" data-testid="flag-count" data-n={n}>
            {shown}
          </span>
          <span className="badge-unit" aria-hidden="true">
            {n === 1 ? 'FLAG' : 'FLAGS'}
          </span>
        </div>
        <div>
          <h2 id="hero-title" className="hero-level">
            {noData ? 'Nothing to check yet' : HEAD[sev]}
          </h2>
          <p className="hero-line">{j.statement}</p>
        </div>
        <FaceIcon face={noData ? 'neutral' : level.face} size={76} />
      </div>
      {j.reasons.length > 0 && <p className="hero-fine">{j.reasons.join(' · ')}</p>}
      {top && (
        <dl className="hero-main">
          <dt>Most serious</dt>
          <dd>
            <span>
              {title(top.drugs[0])} + {title(top.drugs[1])}
            </span>
            <span className="chip" style={{ ['--chip' as string]: SEVERITY[sevKey(top.level)].soft }}>
              {top.level.toLowerCase()}
            </span>
          </dd>
        </dl>
      )}
      {risk != null && (
        <div style={{ display: 'grid', gap: 6 }}>
          <div className="bar" aria-hidden="true" style={{ background: 'rgb(255 255 255 / 0.5)' }}>
            <i style={{ width: `${Math.min(100, risk * 100)}%`, background: 'var(--ink)' }} />
          </div>
          <p className="hero-fine">Combined flag weight {pct(risk)}: a noisy-OR over assumed weights, not a chance of harm.</p>
        </div>
      )}
      <ul className="hero-chips" aria-label="The circle at a glance">
        {chips.map(({ Icon, text }) => (
          <li key={text}>
            <Icon size={20} strokeWidth={1.75} aria-hidden="true" />
            <span className="tnum">{text}</span>
          </li>
        ))}
      </ul>
      <p className="hero-fine">Flags are for discussion with a prescriber or pharmacist. No flag does not mean safe. DDInter 2.0 · FDA CYP table.</p>
    </section>
  );
}
