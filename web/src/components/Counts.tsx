import { Calculator } from 'lucide-react';
import { Async } from './Async';
import { title } from '../lib/format';
import { tr } from '../lib/i18n';
import { useApp, useLoad } from '../state';

/** Plain counts over the record. Not advice, not a score of the person. Lines that have nothing to say are left out. */
export function Counts(): React.JSX.Element {
  const app = useApp();
  const counts = useLoad((a) => a.api.counts(), [app.rev]);
  return (
    <section className="card" aria-labelledby="counts-title" data-testid="counts">
      <div className="card-head"><h2 id="counts-title">{tr('How the record adds up')}</h2><Calculator size={20} aria-hidden="true" /></div>
      <Async state={counts}>
        {(c) => (
          <ul className="steps">
            <li><span>{c.load.medicines} {tr('medicines')} · {c.load.times_of_day} {tr('times of day')} · {c.load.special_directions} {tr('with a special direction')}</span></li>
            {c.anticholinergic.medicines.length > 0 && (
              <li><span>{tr('Anticholinergic score')}: {c.anticholinergic.total} ({c.anticholinergic.medicines.map((m) => `${title(m.drug)} ${m.score}`).join(', ')})</span></li>
            )}
            {c.coverage.pairs_possible > 0 && (
              <li><span>{c.coverage.rated + c.coverage.unrated} / {c.coverage.pairs_possible} {tr('pairs listed by the source')}</span></li>
            )}
            {c.reading.saved > 0 && <li><span>{tr(c.reading.statement)}</span></li>}
          </ul>
        )}
      </Async>
    </section>
  );
}
