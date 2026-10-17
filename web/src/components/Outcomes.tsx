import { BarChart3 } from 'lucide-react';
import { Async } from './Async';
import { useT } from '../lib/i18n';
import { useApp, useLoad } from '../state';

/** The last seven days in counts, from the record: doses marked against doses due, and what is flagged or unseen now. Counts only: no score, no comparison. */
export function Outcomes(): React.JSX.Element {
  const app = useApp();
  const t = useT();
  const state = useLoad((a) => a.api.outcomes(a.now()), [app.warp]);
  return (
    <details className="card inspect" data-testid="outcomes">
      <summary><BarChart3 size={18} aria-hidden="true" /> {t('The last 7 days, in counts')}</summary>
      <Async state={state}>
        {(o) => (
          <>
            <ul className="plain">
              <li data-testid="out-given">{o.doses_marked_given} {t('of')} {o.doses_due} {t('doses due were marked as given')}{o.doses_not_marked > 0 ? ` (${o.doses_not_marked} ${t('not marked')})` : ''}</li>
              <li>{o.entries_recorded} {t('entries recorded')}{o.entries_marked_mistake > 0 ? `, ${o.entries_marked_mistake} ${t('marked as entered by mistake')}` : ''}</li>
              <li>{o.flagged_now} {t('interaction flags and')} {o.possible_duplicates_now} {t('possible duplicates on the record now')}</li>
              <li>{o.changes_not_yet_seen} {t('changes some carer has not yet seen')}</li>
              <li data-testid="out-caught">{o.double_doses_stopped} {t('double doses stopped (a second carer tried to mark a dose already marked)')} · {o.changes_seen_late} {t('changes seen more than 4 hours after they were made')}</li>
            </ul>
            <p className="muted small">{t('Counts of what people recorded in this circle. A dose that was taken but not marked counts as not marked. This says nothing about health and is not compared with anyone else.')}</p>
          </>
        )}
      </Async>
    </details>
  );
}
