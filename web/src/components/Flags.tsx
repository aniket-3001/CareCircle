import { Route } from 'lucide-react';
import type { CheckResult } from '../api/types';
import { SEVERITY, sevKey } from '../design/levels';
import { title } from '../lib/format';
import { Pill, type Tone } from './Pill';

const TONE: Record<string, Tone> = { major: 'bad', moderate: 'warn', minor: 'minor', unrated: 'mute' };

/** Every flag with its source and the graph pattern behind it. Unrated pairs are shown as unrated, never as safe. */
export function Flags({ check }: { check: CheckResult }): React.JSX.Element {
  const none = !check.direct.length && !check.enzyme_paths.length && !check.unrated.length;
  if (none) return <p className="muted">No flags from the reference data. That is not a statement of safety.</p>;
  return (
    <div className="stack">
      {check.direct.map((f) => {
        const k = sevKey(f.level);
        return (
          <div key={f.drugs.join('+')} className={`flag flag--${k}`}>
            <div className="row row--wrap">
              <b>
                {title(f.drugs[0])} + {title(f.drugs[1])}
              </b>
              <Pill tone={TONE[k]}>{SEVERITY[k].name.toLowerCase()}</Pill>
            </div>
            <span className="muted small">Source: {f.source}. Discuss with a prescriber or pharmacist.</span>
            <code>{`(a:Drug)-[:INTERACTS {level:'${f.level}'}]-(b:Drug)`}</code>
          </div>
        );
      })}
      {check.enzyme_paths.map((f) => (
        <div key={f.path} className="flag flag--path">
          <div className="row row--wrap">
            <b>{f.meaning.charAt(0).toUpperCase() + f.meaning.slice(1)}</b>
            <Pill tone="info">
              <Route size={12} aria-hidden="true" /> enzyme path
            </Pill>
          </div>
          <span className="muted small">
            {f.source}
            {f.also_in_ddinter ? ' · also listed in DDInter' : ''}
          </span>
          <code>{f.path}</code>
        </div>
      ))}
      {check.unrated.map((f) => (
        <div key={f.drugs.join('+')} className="flag flag--unknown">
          <div className="row row--wrap">
            <b>
              {title(f.drugs[0])} + {title(f.drugs[1])}
            </b>
            <Pill>listed, severity unrated</Pill>
          </div>
          <span className="muted small">Unrated is not the same as safe. Source: {f.source}</span>
        </div>
      ))}
    </div>
  );
}
