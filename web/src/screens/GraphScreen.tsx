import { RotateCcw } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Async } from '../components/Async';
import { AskGraph } from '../components/AskGraph';
import { PageHead } from '../components/PageHead';
import { Pill } from '../components/Pill';
import { Inspector } from '../graph/Inspector';
import { KnowledgeGraph, type Selection } from '../graph/KnowledgeGraph';
import { ALL_LAYERS, LAYER_LABEL, visibleGraph, type Layer } from '../graph/model';
import { title } from '../lib/format';
import { useApp, useLoad } from '../state';
import { tr } from '../lib/i18n';

const LAYER_DOT: Record<Layer, string> = { people: 'var(--c-carer)', entries: 'var(--c-dose)', history: 'var(--c-dose-old)', enzymes: 'var(--c-enzyme)' };

export function GraphScreen(): React.JSX.Element {
  const app = useApp();
  const graph = useLoad((a) => a.api.graph(a.now(), true), [app.warp]);
  const hubs = useLoad((a) => a.api.hubs());
  const [layers, setLayers] = useState<Set<Layer>>(new Set(ALL_LAYERS));
  const [sel, setSel] = useState<Selection>(null);
  const [replay, setReplay] = useState(0);

  const visible = useMemo(() => (graph.data ? visibleGraph(graph.data, layers) : { nodes: [], edges: [] }), [graph.data, layers]);
  const toggle = (l: Layer) => setLayers((cur) => { const n = new Set(cur); if (n.has(l)) n.delete(l); else n.add(l); return n; });

  return (
    <div className="screen">
      <PageHead
        crumb={tr('As stored in FalkorDB')}
        title={tr('The circle as a graph')}
        lede={tr('Click a node or line for details. Coral: major interaction. Orange: moderate. Blue: enzyme path.')}
        action={
          <button type="button" className="btn btn--soft btn--sm" onClick={() => setReplay((r) => r + 1)}>
            <RotateCcw size={16} aria-hidden="true" /> {tr('Replay animation')}
          </button>
        }
      />
      <div style={{ marginTop: 18, display: 'grid', gap: 16 }}>
        <Async state={graph}>
          {(g) => (
            <>
              <fieldset className="chips" aria-label={tr('Layers')}>
                {ALL_LAYERS.map((l) => (
                  <label key={l} className="fchip">
                    <input type="checkbox" checked={layers.has(l)} onChange={() => toggle(l)} />
                    <i style={{ ['--dot' as string]: LAYER_DOT[l] }} />
                    <span>{LAYER_LABEL[l]}</span>
                  </label>
                ))}
              </fieldset>
              <div className="layout-graph">
                <KnowledgeGraph visible={visible} selection={sel} onSelect={setSel} replayKey={replay} />
                <Inspector graph={g} selection={sel} onSelect={setSel} />
              </div>
            </>
          )}
        </Async>
        <details className="inspect" data-testid="inspect">
          <summary>{tr('Inspect the graph: rankings, groups, paths and the Cypher behind them (for developers and judges)')}</summary>
          <p className="muted small">{tr('These rankings describe how the records are connected in this graph. They say nothing about which medicine matters medically.')}</p>
        <Async state={hubs}>
          {(h) => (
            <div className="layout layout--even">
              <section className="card" aria-labelledby="rh-title" style={{ alignContent: 'start' }}>
                <h2 id="rh-title">{tr('Most hazard-connected in this regimen')}</h2>
                <p className="muted small">{tr('Medicines with the most interaction lines on this list.')}</p>
                {h.regimen_hubs.rows.length === 0 ? (
                  <p className="muted">{tr('No hazard lines inside this regimen.')}</p>
                ) : (
                  <div className="rows">
                    {h.regimen_hubs.rows.map((r) => (
                      <div key={r.drug} className="item">
                        <span className="item__title">{title(r.drug)}</span>
                        <Pill tone="warn">{r.hazards_in_regimen} hazard{r.hazards_in_regimen === 1 ? '' : 's'}</Pill>
                      </div>
                    ))}
                  </div>
                )}
                <code className="code">{h.regimen_hubs.cypher}</code>
              </section>
              <section className="card" aria-labelledby="pw-title" style={{ alignContent: 'start' }} data-testid="pathways">
                <h2 id="pw-title">{tr('Medicines that share a route')}</h2>
                <p className="muted small">{tr('Medicines cleared by, or affecting, the same liver enzyme or transporter.')}</p>
                {h.pathways.groups.length === 0 ? (
                  <p className="muted">{tr('No two medicines on record share a route in the tables.')}</p>
                ) : (
                  <div className="rows">
                    {h.pathways.groups.map((g) => (
                      <div key={g.enzyme} className="item" data-testid="pathway">
                        <div>
                          <div className="item__title">{g.enzyme} <span className="muted small">({g.kind === 'transporter' ? tr('transporter') : tr('enzyme')})</span></div>
                          <div className="item__sub">{g.members.map((m) => `${title(m.drug)} (${m.roles.join(', ')})`).join('; ')}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                {h.pathways.uncovered.length > 0 && <p className="muted small">{tr('Not covered by the tables')}: {h.pathways.uncovered.map(title).join(', ')}.</p>}
                <code className="code">{h.pathways.cypher}</code>
              </section>
              <section className="card" aria-labelledby="gh-title" style={{ alignContent: 'start' }}>
                <h2 id="gh-title">{tr('Hub medicines across the reference graph')}</h2>
                <p className="muted small">{tr('PageRank over interaction pairs: medicines in the most interactions.')}</p>
                <div className="rows">
                  {h.global_hubs.rows.map((r, i) => (
                    <div key={r.drug} className="item">
                      <span>
                        <span className="muted tnum">{i + 1}.</span> <b>{title(r.drug)}</b>
                      </span>
                      <span className="muted tnum">{r.score}</span>
                    </div>
                  ))}
                </div>
                <code className="code">{h.global_hubs.cypher}</code>
              </section>
            </div>
          )}
        </Async>
        <AskGraph />
        </details>
      </div>
    </div>
  );
}
