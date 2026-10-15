import { Async } from '../components/Async';
import { Flags } from '../components/Flags';
import { Pill } from '../components/Pill';
import { Verdict } from '../components/Verdict';
import { ago, nameOf, title } from '../lib/format';
import { useApp, useLoad } from '../state';

const SOURCE = { typed: 'typed in', photo: 'from a photo', voice: 'from a voice note', document: 'from a document' } as const;

export function TodayScreen(): React.JSX.Element {
  const app = useApp();
  const state = useLoad((a) => a.api.check());
  return (
    <div className="screen">
      <h1 className="headline">What the record says today</h1>
      <Async state={state}>
        {(c) => (
          <>
            <Verdict check={c} />
            <section className="card" aria-labelledby="reg-title">
              <div className="row row--between">
                <h2 className="card__title" id="reg-title">On record for {title(app.session.person)}</h2>
                <Pill tone="info">{c.regimen.length} medicines</Pill>
              </div>
              {c.regimen.length === 0 ? (
                <p className="muted">Nothing yet. Add a medicine from a photo, a voice note, a document or by typing.</p>
              ) : (
                <div className="rows">
                  {c.regimen.map((r) => (
                    <div key={r.id} className="item">
                      <div>
                        <div className="item__title">{title(r.drug)} <span className="muted">{r.dose_text} {r.freq_text}</span></div>
                        <div className="item__sub">
                          added by {nameOf(r.by)} {SOURCE[r.source]}, {ago(r.since, app.now())}
                        </div>
                        {r.quote && <div className="item__sub">“{r.quote}”</div>}
                      </div>
                      <button type="button" className="button button--quiet button--small" onClick={() => app.go('graph')}>
                        See in graph
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <button type="button" className="button button--secondary button--small" style={{ justifySelf: 'start' }} onClick={() => app.go('add')}>
                Add a medicine
              </button>
            </section>
            {(c.direct.length > 0 || c.enzyme_paths.length > 0 || c.unrated.length > 0) && (
              <section className="card" aria-labelledby="flags-title">
                <h2 className="card__title" id="flags-title">Flags, with their sources</h2>
                <Flags check={c} />
                <p className="muted">{c.notice}</p>
              </section>
            )}
          </>
        )}
      </Async>
    </div>
  );
}
