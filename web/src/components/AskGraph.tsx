import { useState } from 'react';
import type { GNode, GPath, Unlinked } from '../api/types';
import { tr } from '../lib/i18n';
import { useApp, useLoad } from '../state';
import { Async } from './Async';
import { Pill, Spinner } from './Pill';
import { Segmented } from './Segmented';

const show = (n: GNode): string => (n.title && n.title !== n.ref ? `${n.label} · ${n.title}` : `${n.label} · ${n.ref}`);

/** Said beside a ranking when most records are not linked to anything, so it is not read as a finding. The counts come from the server; the sentence is built here, so it is translated. */
function Shallow({ u }: { u?: Unlinked }): React.JSX.Element | null {
  if (!u) return null;
  return <p className="muted small" data-testid="ag-shallow">{`${u.records} ${tr('of')} ${u.of} ${tr('records are not linked to anything here, so these rankings are shallow.')}`}</p>;
}

/** The graph-algorithm operations on this circle's own graph, asked in plain words. Every figure is computed by FalkorDB on the server; the Cypher that ran is printed under each. */
export function AskGraph(): React.JSX.Element {
  const app = useApp();
  const [metric, setMetric] = useState<'pagerank' | 'harmonic' | 'betweenness'>('pagerank');
  const [method, setMethod] = useState<'wcc' | 'labelpropagation'>('wcc');
  const influence = useLoad((a) => a.api.influence(metric), [metric]);
  const groups = useLoad((a) => a.api.communities(method), [method]);
  const nodes = useLoad((a) => a.api.influence('pagerank', 50));
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [busy, setBusy] = useState(false);
  const [path, setPath] = useState<GPath | null>(null);
  const [err, setErr] = useState('');

  const find = async (list: GNode[]): Promise<void> => {
    const a = list[Number(from)];
    const b = list[Number(to)];
    if (!a || !b) return;
    setBusy(true);
    setErr('');
    setPath(null);
    try {
      setPath(await app.api.path(a.ref, b.ref, a.label, b.label));
    } catch (e) {
      setErr(e instanceof Error ? e.message : tr('Could not ask the graph'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="layout layout--even" style={{ marginTop: 0 }} data-testid="ask-graph">
      <section className="card" aria-labelledby="ag-infl" style={{ alignContent: 'start' }}>
        <h2 id="ag-infl">{tr('What the record hangs on')}</h2>
        <p className="muted small">{tr('PageRank: records that many others point to. Reach: records from which the rest of the graph can be reached fastest, following the links. Bridges: records that many shortest routes between other records pass through.')}</p>
        <p className="muted small" data-testid="ag-caption">{tr('These rankings describe how the records are connected in this graph. They say nothing about which medicine matters medically.')}</p>
        <Segmented name="ag-metric" label={tr('Measure')} value={metric} onChange={setMetric}
          options={[{ value: 'pagerank', label: 'PageRank' }, { value: 'harmonic', label: tr('Reach') }, { value: 'betweenness', label: tr('Bridges') }]} />
        <Async state={influence}>
          {(r) => (
            <>
              {r.rows.length === 0 ? <p className="muted">{tr('Nothing to rank yet.')}</p> : (
                <div className="rows" data-testid="ag-influence">
                  {r.rows.map((x, i) => (
                    <div key={`${x.label}:${x.ref}`} className="item">
                      <span><span className="muted tnum">{i + 1}.</span> <b>{show(x)}</b></span>
                      <span className="muted tnum">{x.score}</span>
                    </div>
                  ))}
                </div>
              )}
              <Shallow u={r.unlinked} />
              {r.metric === 'betweenness' && <p className="muted small" data-testid="ag-computed">{tr('Computed exactly by this server from the links stored in FalkorDB.')}</p>}
              <code className="code">{r.cypher}</code>
            </>
          )}
        </Async>
      </section>

      <section className="card" aria-labelledby="ag-groups" style={{ alignContent: 'start' }}>
        <h2 id="ag-groups">{tr('What belongs together')}</h2>
        <p className="muted small">{tr('Groups of records that are linked to each other. Connected parts shows the separate islands; communities splits a large connected part.')}</p>
        <Segmented name="ag-method" label={tr('Grouping')} value={method} onChange={setMethod}
          options={[{ value: 'wcc', label: tr('Connected parts') }, { value: 'labelpropagation', label: tr('Communities') }]} />
        <Async state={groups}>
          {(r) => (
            <>
              <Shallow u={r.unlinked} />
              {r.groups.length === 0 ? <p className="muted">{tr('Nothing to group yet.')}</p> : (
                <div className="rows" data-testid="ag-groups">
                  {r.groups.map((g) => (
                    <div key={g.group} className="item">
                      <span>{Object.entries(g.kinds).map(([k, n]) => `${n} ${k}`).join(' · ')}</span>
                      <Pill tone="info">{g.size}</Pill>
                    </div>
                  ))}
                </div>
              )}
              <code className="code">{r.cypher}</code>
            </>
          )}
        </Async>
      </section>

      <section className="card" aria-labelledby="ag-path" style={{ gridColumn: '1 / -1', alignContent: 'start' }}>
        <h2 id="ag-path">{tr('How are two records connected?')}</h2>
        <p className="muted small">{tr('The shortest chain of links between them, whichever way the links point.')}</p>
        <Async state={nodes}>
          {(r) => (
            <>
              <div className="row row--wrap">
                <label className="field">{tr('From')}
                  <select value={from} onChange={(e) => setFrom(e.target.value)} data-testid="ag-from">
                    <option value="">{tr('Choose…')}</option>
                    {r.rows.map((x, i) => <option key={`${x.label}:${x.ref}`} value={i}>{show(x)}</option>)}
                  </select>
                </label>
                <label className="field">{tr('To')}
                  <select value={to} onChange={(e) => setTo(e.target.value)} data-testid="ag-to">
                    <option value="">{tr('Choose…')}</option>
                    {r.rows.map((x, i) => <option key={`${x.label}:${x.ref}`} value={i}>{show(x)}</option>)}
                  </select>
                </label>
                <button type="button" className="btn btn--soft btn--sm" disabled={busy || from === '' || to === ''} onClick={() => void find(r.rows)} data-testid="ag-find">
                  {tr('Find the path')}
                </button>
                {busy && <Spinner />}
              </div>
              {err && <p className="muted" role="alert">{err}</p>}
              {path && (
                path.found ? (
                  <div data-testid="ag-result">
                    <p className="muted small">{path.length === 0 ? tr('That is the same record.') : `${path.length} ${path.length === 1 ? tr('step') : tr('steps')}`}</p>
                    <ol className="rows">
                      {path.path.map((n, i) => (
                        <li key={`${n.label}:${n.ref}:${i}`} className="item">
                          <b>{show(n)}</b>
                          {path.relationships && i < path.relationships.length && <Pill tone="info">{path.relationships[i]}</Pill>}
                        </li>
                      ))}
                    </ol>
                    {path.cypher && <code className="code">{path.cypher}</code>}
                  </div>
                ) : (
                  <p className="muted" data-testid="ag-none">{path.reason === undefined ? tr('No connection found.') : path.reason}</p>
                )
              )}
            </>
          )}
        </Async>
      </section>
    </div>
  );
}
