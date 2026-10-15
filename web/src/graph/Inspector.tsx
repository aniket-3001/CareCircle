import { useEffect, useState } from 'react';
import type { CareGraph, GraphEdge, GraphNode } from '../api/types';
import { Pill, type Tone } from '../components/Pill';
import { Sheet } from '../components/Sheet';
import { KIND, neighbours, relationWord } from './model';
import type { Selection } from './KnowledgeGraph';

const TONE: Record<string, Tone> = { patient: 'info', carer: 'info', dose: 'ok', dose_old: 'mute', drug: 'warn', drug_old: 'mute', enzyme: 'info' };

export function useWide(): boolean {
  const q = '(min-width: 56rem)';
  const [wide, setWide] = useState(() => window.matchMedia(q).matches);
  useEffect(() => {
    const m = window.matchMedia(q);
    const f = () => setWide(m.matches);
    m.addEventListener('change', f);
    return () => m.removeEventListener('change', f);
  }, []);
  return wide;
}

function Body({ graph, sel, onSelect }: { graph: CareGraph; sel: NonNullable<Selection>; onSelect: (s: Selection) => void }): React.JSX.Element {
  if (sel.type === 'edge') {
    const e = graph.edges.find((x) => x.id === sel.id);
    if (!e) return <p className="muted">That line is no longer in the graph.</p>;
    return <EdgeBody graph={graph} edge={e} onSelect={onSelect} />;
  }
  const n = graph.nodes.find((x) => x.id === sel.id);
  if (!n) return <p className="muted">That item is no longer in the graph.</p>;
  return <NodeBody graph={graph} node={n} onSelect={onSelect} />;
}

function Rows({ meta }: { meta: [string, string][] }): React.JSX.Element {
  return (
    <dl className="meta" data-testid="meta">
      {meta.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function NodeBody({ graph, node, onSelect }: { graph: CareGraph; node: GraphNode; onSelect: (s: Selection) => void }): React.JSX.Element {
  const ns = neighbours(graph, node.id).filter((x) => !x.edge.weak || x.node.kind !== 'drug' || node.kind !== 'dose');
  return (
    <div className="stack">
      <div className="inspector__head">
        <div style={{ ['--nc' as string]: KIND[node.kind].color }}>
          <div className="inspector__title" role="heading" aria-level={3}>{node.label}</div>
          <Pill tone={TONE[node.kind] ?? 'mute'}>{KIND[node.kind].word}</Pill>
        </div>
      </div>
      <p>{node.summary}</p>
      <Rows meta={node.meta} />
      {ns.length > 0 && (
        <section>
          <h4 className="section-title">Connected to</h4>
          <ul className="neighbours">
            {ns.map((x) => (
              <li key={x.edge.id + x.node.id}>
                <button type="button" style={{ ['--nc' as string]: KIND[x.node.kind].color }} onClick={() => onSelect({ type: 'node', id: x.node.id })}>
                  <span className="dot" />
                  <span>
                    <span className="muted">{relationWord(x.edge, x.outgoing)}</span> <b>{x.node.label}</b>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      <section>
        <h4 className="section-title">How it is stored in the graph</h4>
        <code className="code">{node.cypher}</code>
      </section>
    </div>
  );
}

function EdgeBody({ graph, edge, onSelect }: { graph: CareGraph; edge: GraphEdge; onSelect: (s: Selection) => void }): React.JSX.Element {
  const a = graph.nodes.find((n) => n.id === edge.source);
  const b = graph.nodes.find((n) => n.id === edge.target);
  const tone: Tone = edge.level === 'major' ? 'bad' : edge.level === 'moderate' ? 'warn' : edge.kind === 'acked' ? 'ok' : 'info';
  return (
    <div className="stack">
      <div>
        <div className="inspector__title" role="heading" aria-level={3}>
          {a?.label} <span className="muted">{edge.label}</span> {b?.label}
        </div>
        <Pill tone={tone}>{edge.kind === 'interacts' ? `${edge.level ?? 'unrated'} interaction` : edge.kind}</Pill>
      </div>
      <p>{edge.summary}</p>
      {edge.meta.length > 0 && <Rows meta={edge.meta} />}
      <section>
        <h4 className="section-title">Ends of this line</h4>
        <ul className="neighbours">
          {[a, b].map((n) =>
            n ? (
              <li key={n.id}>
                <button type="button" style={{ ['--nc' as string]: KIND[n.kind].color }} onClick={() => onSelect({ type: 'node', id: n.id })}>
                  <span className="dot" />
                  <b>{n.label}</b>
                </button>
              </li>
            ) : null,
          )}
        </ul>
      </section>
    </div>
  );
}

/** Docked beside the graph on wide screens, a bottom sheet on narrow ones. */
export function Inspector({ graph, selection, onSelect }: { graph: CareGraph; selection: Selection; onSelect: (s: Selection) => void }): React.JSX.Element | null {
  const wide = useWide();
  if (wide) {
    return (
      <aside className="card inspector--docked" aria-label="Details" data-testid="inspector">
        {selection ? (
          <Body graph={graph} sel={selection} onSelect={onSelect} />
        ) : (
          <div className="empty">
            <b>Nothing selected</b>
            <span>Click a node or a line in the graph to see what it is, where it came from and how it is connected, in plain words.</span>
          </div>
        )}
      </aside>
    );
  }
  return (
    <Sheet open={selection !== null} title="Details" onClose={() => onSelect(null)}>
      <div data-testid="inspector">{selection && <Body graph={graph} sel={selection} onSelect={onSelect} />}</div>
    </Sheet>
  );
}
