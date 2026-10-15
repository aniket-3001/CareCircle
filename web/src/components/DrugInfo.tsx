import { BookOpen, ExternalLink } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { DrugInfo as Info } from '../api/types';
import { title } from '../lib/format';
import { useApp } from '../state';
import { Pill, Spinner } from './Pill';
import { Sheet } from './Sheet';
import { tr } from '../lib/i18n';

/** What public sources say about one medicine, in their own words and with their source. Only the medicine's name is sent out. */
export function DrugInfo({ drug }: { drug: string }): React.JSX.Element {
  const app = useApp();
  const [open, setOpen] = useState(false);
  const [info, setInfo] = useState<Info | null | 'error'>(null);
  useEffect(() => {
    if (open && info === null) app.api.drugInfo(drug).then(setInfo, () => setInfo('error'));
  }, [open, info, app.api, drug]);
  return (
    <>
      <button type="button" className="icon-btn" aria-label={`About ${title(drug)}`} onClick={() => setOpen(true)}><BookOpen size={16} aria-hidden="true" /></button>
      <Sheet open={open} title={`About ${title(drug)}`} onClose={() => setOpen(false)}>
        {info === null && <Spinner />}
        {info === 'error' && <p className="muted">{tr('Could not load this just now. Try again in a moment.')}</p>}
        {info && info !== 'error' && (
          <div className="stack">
            <div className="row row--wrap">
              <Pill tone={info.in_interaction_reference ? 'ok' : 'mute'}>{info.in_interaction_reference ? 'covered by the interaction data' : 'not in the interaction data'}</Pill>
              {info.rxnorm && <Pill tone="info">RxNorm {info.rxnorm.rxcui}</Pill>}
            </div>
            {info.label ? (
              <>
                {info.label.boxed_warning && <div className="banner banner--bad"><b>{tr("The label's boxed warning:")}</b> {info.label.boxed_warning}</div>}
                {info.label.indications && <p><b>{tr('The label says it is used for:')}</b> {info.label.indications}</p>}
                <p className="muted small">{info.label.source}. Label version {info.label.effective}. <a href={info.label.url} target="_blank" rel="noreferrer noopener">{tr('Full label')} <ExternalLink size={12} aria-hidden="true" /></a></p>
              </>
            ) : <p className="muted">{info.available ? 'No official label was found for this name.' : 'Live label lookups are switched off here.'}</p>}
            <p className="muted small">{info.note}</p>
          </div>
        )}
      </Sheet>
    </>
  );
}
