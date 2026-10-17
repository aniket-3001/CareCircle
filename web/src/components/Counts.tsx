import { Calculator } from 'lucide-react';
import { Async } from './Async';
import { title } from '../lib/format';
import { tr } from '../lib/i18n';
import { useApp, useLoad } from '../state';

/** Plain counts over the record: how it reads, a short anticholinergic total (a subset, said so), and how much the interaction sources cover. Not advice, not a score of the person. */
export function Counts(): React.JSX.Element {
  const app = useApp();
  const counts = useLoad((a) => a.api.counts(), [app.rev]);
  return (
    <section className="card" aria-labelledby="counts-title" data-testid="counts">
      <div className="card-head"><h2 id="counts-title">{tr('How the record adds up')}</h2><Calculator size={20} aria-hidden="true" /></div>
      <p className="muted small">{tr('Plain counts for a talk with a pharmacist.')}</p>
      <Async state={counts}>
        {(c) => (
          <ul className="steps">
            <li><span>{tr(c.load.statement)}</span></li>
            <li><span>{tr(c.anticholinergic.statement)}{c.anticholinergic.medicines.length > 0 && ` (${c.anticholinergic.medicines.map((m) => `${title(m.drug)} ${m.score}`).join(', ')})`} <span className="muted">· {c.anticholinergic.source}</span></span></li>
            <li><span>{tr(c.coverage.statement)}</span></li>
            <li><span>{tr(c.reading.statement)}</span></li>
          </ul>
        )}
      </Async>
    </section>
  );
}
