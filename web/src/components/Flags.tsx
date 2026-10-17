import { Route } from 'lucide-react';
import type { CheckResult } from '../api/types';
import { SEVERITY, sevKey } from '../design/levels';
import { productName, title } from '../lib/format';
import { Pill, type Tone } from './Pill';
import { tr } from '../lib/i18n';

const TONE: Record<string, Tone> = { major: 'bad', moderate: 'warn', minor: 'minor', unrated: 'mute' };

/** Every flag with its source and the graph pattern behind it. Unrated pairs are shown as unrated, never as safe. */
export function Flags({ check }: { check: CheckResult }): React.JSX.Element {
  const dups = check.duplicates ?? [];
  const none = !check.direct.length && !check.enzyme_paths.length && !check.unrated.length && !dups.length;
  if (none) return <p className="muted">{tr('No flags from the reference data. That is not a statement of safety.')}</p>;
  return (
    <div className="stack">
      {dups.map((d) => (
        <div key={d.ingredient} className="flag flag--path" data-testid="duplicate-flag">
          <div className="row row--wrap">
            <b>{title(d.ingredient)} {tr('is on record more than once')}</b>
            <Pill tone="warn">{tr('possible duplicate')}</Pill>
          </div>
          <span className="muted small">{d.entries.map((e) => `${e.product ? productName(e.product) : tr('recorded as the plain medicine')}${e.dose_text ? ` ${e.dose_text}` : ''}`).join(' · ')}. {tr('It may be the same medicine from two sources. Discuss with a prescriber or pharmacist.')}</span>
        </div>
      ))}
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
            <span className="muted small">{tr('Source:')} {f.source}. {tr('Discuss with a prescriber or pharmacist.')}</span>
            <code>{`(a:Drug)-[:INTERACTS {level:'${f.level}'}]-(b:Drug)`}</code>
          </div>
        );
      })}
      {check.enzyme_paths.map((f) => (
        <div key={f.path} className="flag flag--path">
          <div className="row row--wrap">
            <b>{f.meaning.charAt(0).toUpperCase() + f.meaning.slice(1)}</b>
            <Pill tone="info">
              <Route size={12} aria-hidden="true" /> {f.target === 'transporter' ? 'transporter path' : 'enzyme path'}{f.strength === 'in vitro' ? ' · lab finding' : ''}
            </Pill>
          </div>
          <span className="muted small">
            {f.source}
            {f.also_in_ddinter ? ' · also listed in DDInter' : ''}
          </span>
          <code>{f.path}</code>
        </div>
      ))}
      {check.unrated.length > 0 && (
        <details className="unrated-fold" data-testid="unrated-fold">
          <summary>
            {check.unrated.length} {check.unrated.length === 1 ? tr('pair is listed by the source without a severity') : tr('pairs are listed by the source without a severity')} ({tr('unrated is not the same as safe')})
          </summary>
          <div className="stack">
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
        </details>
      )}
    </div>
  );
}
