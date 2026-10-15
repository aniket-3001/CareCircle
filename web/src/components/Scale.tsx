import type { CheckResult } from '../api/types';
import { SEVERITY, sevKey, type SeverityKey } from '../design/levels';

const ORDER: SeverityKey[] = ['none', 'minor', 'moderate', 'major', 'unrated'];

/** The severity scale (after The Vayu Project's AQI scale): what each colour means and how many flags of each kind are on record. */
export function Scale({ check }: { check: CheckResult }): React.JSX.Element {
  const count: Record<SeverityKey, number> = { none: 0, minor: 0, moderate: 0, major: 0, unrated: check.unrated.length };
  for (const f of check.direct) count[sevKey(f.level)] += 1;
  return (
    <section className="card" aria-labelledby="scale-title">
      <h2 id="scale-title">How to read a flag</h2>
      <div className="scale">
        <div className="scale-bar" aria-hidden="true">
          {ORDER.map((k) => (
            <i key={k} style={{ background: SEVERITY[k].solid }} />
          ))}
        </div>
        <div className="scale-labels">
          {ORDER.map((k) => (
            <span key={k} className={count[k] > 0 && k !== 'none' ? 'on' : ''}>
              {SEVERITY[k].name}
              <small>{k === 'none' ? 'nothing listed' : `${count[k]} on record`}</small>
            </span>
          ))}
        </div>
      </div>
      <p className="muted small">Severity is as listed by DDInter 2.0. Unrated means the source lists the pair without a severity: that is not the same as safe. Enzyme paths come from the FDA table and are shown separately.</p>
    </section>
  );
}
