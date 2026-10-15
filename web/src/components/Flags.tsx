import type { CheckResult } from '../api/types';
import { title } from '../lib/format';
import { Pill } from './Pill';

/** Every flag with its source and the graph pattern behind it. Unrated pairs are shown as unrated, never as safe. */
export function Flags({ check }: { check: CheckResult }): React.JSX.Element {
  const none = !check.direct.length && !check.enzyme_paths.length && !check.unrated.length;
  if (none) return <p className="muted">No flags from the reference data.</p>;
  return (
    <div className="stack">
      {check.direct.map((f) => (
        <div key={f.drugs.join('+')} className={`flag flag--${f.level.toLowerCase()}`}>
          <div className="row row--wrap">
            <b>
              {title(f.drugs[0])} + {title(f.drugs[1])}
            </b>
            <Pill tone={f.level.toLowerCase() === 'major' ? 'bad' : 'warn'}>{f.level}</Pill>
          </div>
          <span className="muted">Source: {f.source}. Discuss with a prescriber or pharmacist.</span>
          <code>{`(a:Drug)-[:INTERACTS {level:'${f.level}'}]-(b:Drug)`}</code>
        </div>
      ))}
      {check.enzyme_paths.map((f) => (
        <div key={f.path} className="flag flag--path">
          <div className="row row--wrap">
            <b>{f.meaning.charAt(0).toUpperCase() + f.meaning.slice(1)}</b>
            <Pill tone="info">enzyme path</Pill>
          </div>
          <span className="muted">
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
          <span className="muted">Unrated is not the same as safe. Source: {f.source}</span>
        </div>
      ))}
    </div>
  );
}
