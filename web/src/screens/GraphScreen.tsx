import { RotateCcw } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Async } from '../components/Async';
import { PageHead } from '../components/PageHead';
import { Pill } from '../components/Pill';
import { Inspector } from '../graph/Inspector';
import { KnowledgeGraph, type Selection } from '../graph/KnowledgeGraph';
import { ALL_LAYERS, LAYER_LABEL, visibleGraph, type Layer } from '../graph/model';
import { title } from '../lib/format';
import { useApp, useLoad } from '../state';

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
        crumb="As stored in FalkorDB"
        title="The circle as a graph"
        lede="People, entries, medicines and liver enzymes. Coral lines are major interactions (they pulse), orange moderate, blue enzyme paths. Click any node or line to read what it is and where it came from."
        action={
          <button type="button" className="btn btn--soft btn--sm" onClick={() => setReplay((r) => r + 1)}>
            <RotateCcw size={16} aria-hidden="true" /> Replay animation
          </button>
        }
      />
      <div style={{ marginTop: 18, display: 'grid', gap: 16 }}>
        <Async state={graph}>
          {(g) => (
            <>
              <fieldset className="chips" aria-label="Layers">
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
        <Async state={hubs}>
          {(h) => (
            <div className="layout layout--even" style={{ marginTop: 0 }}>
              <section className="card" aria-labelledby="rh-title">
                <h2 id="rh-title">Most hazard-connected in this regimen</h2>
                <p className="muted small">Degree and summed weight inside the moderate and major interaction subgraph of the medicines on record.</p>
                {h.regimen_hubs.rows.length === 0 ? (
                  <p className="muted">No hazard lines inside this regimen.</p>
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
              <section className="card" aria-labelledby="gh-title">
                <h2 id="gh-title">Hub medicines across the reference graph</h2>
                <p className="muted small">PageRank over moderate and major interaction pairs: the medicines that sit in the most hazards.</p>
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
      </div>
    </div>
  );
}
