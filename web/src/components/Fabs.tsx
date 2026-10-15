import { Plus } from 'lucide-react';
import { nameOf } from '../lib/format';
import { useApp } from '../state';

/** The round buttons that are always there: add a medicine, and switch who is acting (as in The Vayu Project's dock). */
export function Fabs(): React.JSX.Element {
  const app = useApp();
  const keys = Object.keys(app.session.keys);
  const next = keys[(keys.indexOf(app.session.as) + 1) % keys.length] ?? app.session.as;
  return (
    <div className="fabs">
      {keys.length > 1 && (
        <button type="button" className="fab" onClick={() => app.actAs(next)} aria-label={`Acting as ${nameOf(app.session.as)}. Switch to ${nameOf(next)}`}>
          <span className="av">{nameOf(app.session.as).charAt(0)}</span>
        </button>
      )}
      <button type="button" className="fab fab--primary" onClick={() => app.go('add')} aria-label="Add a medicine">
        <Plus size={24} strokeWidth={2} aria-hidden="true" />
      </button>
    </div>
  );
}
