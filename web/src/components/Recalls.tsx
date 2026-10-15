import { PackageX } from 'lucide-react';
import { Async } from './Async';
import { Pill } from './Pill';
import { title } from '../lib/format';
import { useLoad } from '../state';

/** Ongoing public recalls listed for the medicines on record. Shown as published: whether one applies depends on the pack at home. */
export function Recalls(): React.JSX.Element | null {
  const state = useLoad((a) => a.api.recalls());
  if (state.data && (!state.data.available || state.data.checked.length === 0)) return null;
  return (
    <section className="card" aria-labelledby="recall-title" data-testid="recalls">
      <div className="card-head"><h2 id="recall-title">Recalls to check</h2><PackageX size={20} aria-hidden="true" /></div>
      <Async state={state}>
        {(r) => r.recalls.length === 0 ? (
          <p className="muted">No ongoing recall is listed for the {r.checked.length} medicines on record (openFDA, US recalls). That does not cover every country or every pack.</p>
        ) : (
          <div className="rows">
            {r.recalls.map((x) => (
              <div key={x.number} className="item"><div>
                <div className="item__title">{title(x.drug)} <Pill tone="warn">{x.class || 'recall'}</Pill></div>
                <div className="item__sub">{x.reason}</div>
                <div className="item__sub">{x.product} · {x.firm} · {x.number}</div>
              </div></div>
            ))}
            <p className="muted small">{r.note} Source: {r.recalls[0]?.source}.</p>
          </div>
        )}
      </Async>
    </section>
  );
}
