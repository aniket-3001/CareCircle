import type { CheckResult } from '../api/types';
import { pct } from '../lib/format';

const TONE = { flags: 'bad', partial: 'warn', no_data: 'mute', no_known_conflict: 'ok' } as const;
const HEAD = { flags: 'Possible interactions', partial: 'Not enough to judge', no_data: 'Nothing to check yet', no_known_conflict: 'No known conflict' } as const;

/** The answer to "what does the record say?" in one tile (after Vayu's band tile). Never says "safe". */
export function Verdict({ check }: { check: CheckResult }): React.JSX.Element {
  const j = check.judgement;
  const tone = TONE[j.state];
  const n = check.direct.length + check.enzyme_paths.length;
  const risk = check.regimen_risk;
  return (
    <section className={`verdict verdict--${tone}`} aria-label={`${HEAD[j.state]}. ${j.statement}`} data-testid="verdict" data-state={j.state}>
      <div className="verdict__head">
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          {j.state === 'flags' ? (
            <path d="M12 3 2.5 20h19L12 3Zm0 6v5m0 3h.01" />
          ) : j.state === 'no_known_conflict' ? (
            <path d="M5 12l4 4 10-10" />
          ) : (
            <path d="M12 8v5m0 3h.01M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z" />
          )}
        </svg>
        <h2 className="verdict__state">{HEAD[j.state]}</h2>
      </div>
      {j.state === 'flags' && (
        <p className="verdict__figure" data-testid="flag-count">
          {n}
          <small>{n === 1 ? 'flag' : 'flags'} from the reference data</small>
        </p>
      )}
      <p>{j.statement}</p>
      {j.reasons.map((r) => (
        <p key={r} style={{ fontSize: 'var(--text-footnote)', opacity: 0.85 }}>
          {r}
        </p>
      ))}
      {risk != null && (
        <>
          <div className="bar" aria-hidden="true">
            <i style={{ width: `${Math.min(100, risk * 100)}%` }} />
          </div>
          <p style={{ fontSize: 'var(--text-caption)', opacity: 0.85 }}>
            Combined flag weight {pct(risk)} (noisy-OR over assumed weights: not a probability of harm)
          </p>
        </>
      )}
      <p className="provenance">
        <span>DDInter 2.0 · FDA CYP table · graph query</span>
        <span className="provenance__mode">not advice</span>
      </p>
    </section>
  );
}
