import { Plus, Sparkles } from 'lucide-react';
import { nameOf } from '../lib/format';
import { useT } from '../lib/i18n';
import { useApp } from '../state';

/** The round buttons that are always there (as in The Vayu Project's dock): ask the helper, add a medicine, and (anonymous demo only) switch carer. */
export function Fabs(): React.JSX.Element {
  const app = useApp();
  const t = useT();
  const keys = Object.keys(app.session.keys);
  const next = keys[(keys.indexOf(app.session.as) + 1) % keys.length] ?? app.session.as;
  return (
    <div className="fabs">
      {!app.acct && keys.length > 1 && (
        <button type="button" className="fab" onClick={() => app.actAs(next)} aria-label={`Acting as ${nameOf(app.session.as)}. Switch to ${nameOf(next)}`}>
          <span className="av">{nameOf(app.session.as).charAt(0)}</span>
        </button>
      )}
      <button type="button" className="fab" onClick={() => app.go('add')} aria-label={t('Add a medicine')}>
        <Plus size={22} strokeWidth={2} aria-hidden="true" />
      </button>
      <button type="button" className="fab fab--primary" onClick={() => app.askAssistant()} aria-label={t('Ask the helper')} data-testid="open-assistant">
        <Sparkles size={24} strokeWidth={1.75} aria-hidden="true" />
      </button>
    </div>
  );
}
