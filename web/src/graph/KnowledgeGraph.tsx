import { tr } from '../lib/i18n';
import { forceCollide, forceLink, forceManyBody, forceRadial, forceSimulation, type Simulation, type SimulationLinkDatum, type SimulationNodeDatum } from 'd3-force';
import { Expand, Scan, Minimize2, Minus, Pause, Play, Plus } from 'lucide-react';
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { GraphEdge, GraphNode } from '../api/types';
import { KIND, clip, edgeClass, glyphFor, isFlagged, isMajor, majorDrugs, type Visible } from './model';

export type Selection = { type: 'node' | 'edge'; id: string } | null;

interface SNode extends SimulationNodeDatum {
  id: string;
  data: GraphNode;
}
interface SLink extends SimulationLinkDatum<SNode> {
  data: GraphEdge;
}

const LINK_DISTANCE: Record<string, number> = { for: 80, of: 56, recorded: 140, acked: 120, supersedes: 50, interacts: 120, inhibits: 90, induces: 90, substrate: 80 };
const reduceMotion = (): boolean => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

interface Props {
  visible: Visible;
  selection: Selection;
  onSelect: (s: Selection) => void;
  replayKey: number;
}

/** The circle as a living graph: force-directed orbits, nodes pop in, edges draw themselves, flagged edges carry flowing dashes and major
 *  interactions pulse. Click a node or edge to inspect it, drag nodes, scroll to zoom, drag the background to pan. Everything is also reachable by keyboard. */
export function KnowledgeGraph({ visible, selection, onSelect, replayKey }: Props): React.JSX.Element {
  const wrap = useRef<HTMLDivElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const root = useRef<SVGGElement>(null);
  const [size, setSize] = useState({ w: 640, h: 440 });
  const [hover, setHover] = useState<string | null>(null);
  const [still, setStill] = useState(false);
  const nodeEls = useRef(new Map<string, SVGGElement>());
  const edgeEls = useRef(new Map<string, SVGPathElement[]>());
  const simNodes = useRef<SNode[]>([]);
  const simLinks = useRef<SLink[]>([]);
  const pos = useRef(new Map<string, { x: number; y: number }>());
  const sim = useRef<Simulation<SNode, SLink> | null>(null);
  const view = useRef({ k: 1, x: 0, y: 0 });
  const stretch = useRef(1); // the layout is computed on a circle and stretched sideways on wide cards, so nodes keep their size
  const select = useRef(onSelect);
  select.current = onSelect;

  // ---- full screen (the browser's Fullscreen API on the graph card; Esc leaves)
  const [full, setFull] = useState(false);
  useEffect(() => {
    const f = () => { if (!document.fullscreenElement) setFull(false); };
    document.addEventListener('fullscreenchange', f);
    return () => document.removeEventListener('fullscreenchange', f);
  }, []);
  // If the browser refuses the Fullscreen API, the card still fills the window (the kg--full class), so the button always does what it says.
  const toggleFull = () => {
    if (full) {
      setFull(false);
      if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined);
      return;
    }
    setFull(true);
    void wrap.current?.requestFullscreen?.().catch(() => undefined);
  };

  // ---- size
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: Math.max(280, el.clientWidth), h: Math.max(320, el.clientHeight) }));
    ro.observe(el);
    setSize({ w: Math.max(280, el.clientWidth), h: Math.max(320, el.clientHeight) });
    return () => ro.disconnect();
  }, []);

  // ---- painting: positions and view go straight to the DOM (no React re-render per frame)
  const paint = useCallback(() => {
    for (const n of simNodes.current) nodeEls.current.get(n.id)?.setAttribute('transform', `translate(${(n.x ?? 0) * stretch.current},${n.y ?? 0})`);
    simLinks.current.forEach((l, i) => {
      const s = l.source as SNode, t = l.target as SNode;
      const st = stretch.current, sx = (s.x ?? 0) * st, sy = s.y ?? 0, tx = (t.x ?? 0) * st, ty = t.y ?? 0;
      const dx = tx - sx, dy = ty - sy, len = Math.hypot(dx, dy) || 1;
      const off = (i % 2 === 0 ? 1 : -1) * Math.min(28, len * 0.14);
      const d = `M${sx},${sy} Q${(sx + tx) / 2 - (dy / len) * off},${(sy + ty) / 2 + (dx / len) * off} ${tx},${ty}`;
      edgeEls.current.get(l.data.id)?.forEach((p) => p.setAttribute('d', d));
    });
  }, []);

  const applyView = useCallback((smooth: boolean) => {
    const g = root.current;
    if (!g) return;
    g.style.transition = smooth && !reduceMotion() ? 'transform 0.7s cubic-bezier(0.2,0.9,0.25,1)' : 'none';
    const { k, x, y } = view.current;
    g.style.transform = `translate(${size.w / 2 + x}px, ${size.h / 2 + y}px) scale(${k})`;
  }, [size]);

  const fit = useCallback((smooth = true) => {
    const ns = simNodes.current;
    if (!ns.length) return;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const n of ns) {
      const r = KIND[n.data.kind].r + 22;
      const nx = (n.x ?? 0) * stretch.current;
      x0 = Math.min(x0, nx - r - 14); x1 = Math.max(x1, nx + r + 14);
      y0 = Math.min(y0, (n.y ?? 0) - r); y1 = Math.max(y1, (n.y ?? 0) + r + 46); // room for the label and the legend
    }
    const k = Math.max(0.35, Math.min(1.5, (size.w - 24) / (x1 - x0), (size.h - 24) / (y1 - y0)));
    view.current = { k, x: -((x0 + x1) / 2) * k, y: -((y0 + y1) / 2) * k };
    applyView(smooth);
  }, [size, applyView]);

  // ---- layout: (re)build the simulation when the data or the size changes, keeping positions of nodes that stay
  useEffect(() => {
    stretch.current = Math.max(1, Math.min(1.9, (size.w / size.h) * 0.95));
    const R = Math.max(120, Math.min(size.w / stretch.current, size.h) / 2 - 56);
    const prev = pos.current;
    const nodes: SNode[] = visible.nodes.map((d, i) => {
      const p = prev.get(d.id);
      const a = i * 2.4, r = KIND[d.kind].ring * R * 0.8;
      return { id: d.id, data: d, x: p?.x ?? Math.cos(a) * r, y: p?.y ?? Math.sin(a) * r };
    });
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const links: SLink[] = visible.edges.filter((e) => byId.has(e.source) && byId.has(e.target)).map((e) => ({ source: e.source, target: e.target, data: e }));
    simNodes.current = nodes;
    simLinks.current = links;
    sim.current?.stop();
    const s = forceSimulation<SNode>(nodes)
      .force('link', forceLink<SNode, SLink>(links).id((n) => n.id).distance((l) => LINK_DISTANCE[l.data.kind] ?? 90).strength((l) => (l.data.weak ? 0.06 : l.data.kind === 'interacts' ? 0.18 : 0.3)))
      .force('charge', forceManyBody<SNode>().strength(-340).distanceMax(460))
      .force('radial', forceRadial<SNode>((n) => KIND[n.data.kind].ring * R, 0, 0).strength(0.55))
      .force('collide', forceCollide<SNode>((n) => KIND[n.data.kind].r + (n.data.kind === 'dose' || n.data.kind === 'dose_old' ? 22 : 26)))
      .alphaDecay(0.035);
    sim.current = s;
    const remember = () => { for (const n of nodes) pos.current.set(n.id, { x: n.x ?? 0, y: n.y ?? 0 }); };
    if (reduceMotion()) {
      s.stop();
      s.tick(320);
      remember(); paint(); fit(false);
    } else {
      s.on('tick', () => { paint(); remember(); }).on('end', () => fit(true));
      window.setTimeout(() => fit(true), 900);
    }
    paint();
    return () => { s.stop(); };
  }, [visible, size, paint, fit]);

  // elements are recreated on replay / re-render: put them back where they belong
  useLayoutEffect(() => { paint(); applyView(false); });

  // ---- zoom (wheel, buttons) and pan (background drag)
  const zoomBy = useCallback((f: number, cx = 0, cy = 0) => {
    const v = view.current, k = Math.max(0.3, Math.min(3, v.k * f)), r = k / v.k;
    view.current = { k, x: cx - (cx - v.x) * r, y: cy - (cy - v.y) * r };
    applyView(false);
  }, [applyView]);

  useEffect(() => {
    const el = svg.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const b = el.getBoundingClientRect();
      zoomBy(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX - b.left - size.w / 2, e.clientY - b.top - size.h / 2);
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [zoomBy, size]);

  const toGraph = (e: { clientX: number; clientY: number }) => {
    const b = svg.current!.getBoundingClientRect(), v = view.current;
    return { x: (e.clientX - b.left - size.w / 2 - v.x) / v.k / stretch.current, y: (e.clientY - b.top - size.h / 2 - v.y) / v.k };
  };

  const panning = useRef<{ x: number; y: number; vx: number; vy: number; moved: boolean } | null>(null);
  const onBackdropDown = (e: React.PointerEvent) => {
    (e.target as Element).setPointerCapture(e.pointerId);
    panning.current = { x: e.clientX, y: e.clientY, vx: view.current.x, vy: view.current.y, moved: false };
  };
  const onBackdropMove = (e: React.PointerEvent) => {
    const p = panning.current;
    if (!p) return;
    if (Math.abs(e.clientX - p.x) + Math.abs(e.clientY - p.y) > 3) p.moved = true;
    view.current = { ...view.current, x: p.vx + e.clientX - p.x, y: p.vy + e.clientY - p.y };
    applyView(false);
  };
  const onBackdropUp = () => {
    if (panning.current && !panning.current.moved) onSelect(null);
    panning.current = null;
  };

  // ---- dragging a node (a short press without movement is a click)
  const drag = useRef<{ n: SNode; sx: number; sy: number; moved: boolean } | null>(null);
  const onNodeDown = (e: React.PointerEvent, id: string) => {
    e.stopPropagation();
    const n = simNodes.current.find((x) => x.id === id);
    if (!n) return;
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    drag.current = { n, sx: e.clientX, sy: e.clientY, moved: false };
    const g = toGraph(e);
    n.fx = g.x; n.fy = g.y;
    sim.current?.alphaTarget(0.25).restart();
  };
  const onNodeMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    if (Math.abs(e.clientX - d.sx) + Math.abs(e.clientY - d.sy) > 4) d.moved = true;
    const g = toGraph(e);
    d.n.fx = g.x; d.n.fy = g.y;
    if (reduceMotion()) { d.n.x = g.x; d.n.y = g.y; paint(); }
  };
  const onNodeUp = () => {
    const d = drag.current;
    if (!d) return;
    d.n.fx = null; d.n.fy = null;
    sim.current?.alphaTarget(0);
    if (!d.moved) onSelect({ type: 'node', id: d.n.id });
    drag.current = null;
  };

  // ---- highlighting
  const focusId = hover ?? (selection?.type === 'node' ? selection.id : null);
  const focusEdge = selection?.type === 'edge' ? visible.edges.find((e) => e.id === selection.id) : undefined;
  const hi = useMemo(() => {
    const s = new Set<string>();
    if (focusEdge) { s.add(focusEdge.source); s.add(focusEdge.target); }
    if (focusId) {
      s.add(focusId);
      for (const e of visible.edges) { if (e.source === focusId) s.add(e.target); if (e.target === focusId) s.add(e.source); }
    }
    return s;
  }, [focusId, focusEdge, visible.edges]);
  const dim = hi.size > 0;
  const major = useMemo(() => majorDrugs(visible.edges), [visible.edges]);
  const kinds = useMemo(() => [...new Set(visible.nodes.map((n) => n.kind))], [visible.nodes]);

  const order = new Map<string, number>();
  const nodeDelay = (n: GraphNode): number => {
    const k = KIND[n.kind].order, i = order.get(n.kind) ?? 0;
    order.set(n.kind, i + 1);
    return k * 0.1 + i * 0.045;
  };

  return (
    <div ref={wrap} className={`card kg${still ? ' kg--still' : ''}${full ? ' kg--full' : ''}`} data-testid="knowledge-graph">
      <svg
        ref={svg}
        className={`kg__svg${dim ? ' kg--dim' : ''}`}
        role="group"
        aria-label={tr('Knowledge graph of this circle. Tab to a node and press Enter to inspect it.')}
        viewBox={`0 0 ${size.w} ${size.h}`}
      >
        <rect className="kg__backdrop" width={size.w} height={size.h} onPointerDown={onBackdropDown} onPointerMove={onBackdropMove} onPointerUp={onBackdropUp} />
        <g ref={root} key={replayKey}>
          <g>
            {visible.edges.map((e, i) => {
              const reg = (el: SVGPathElement | null) => {
                const cur = edgeEls.current.get(e.id) ?? [];
                if (el && !cur.includes(el)) edgeEls.current.set(e.id, [...cur.filter((x) => x.isConnected), el]);
              };
              const picked = selection?.type === 'edge' && selection.id === e.id;
              const touches = focusId !== null && (e.source === focusId || e.target === focusId);
              const flow = isFlagged(e);
              return (
                <g key={e.id}>
                  <path ref={reg} pathLength={1} className={`${edgeClass(e)} kg__draw${touches || picked ? ' kg__edge--hi' : ''}${picked ? ' kg__edge--picked' : ''}`} style={{ ['--d' as string]: `${0.55 + i * 0.03}s` }} />
                  {flow && <path ref={reg} className={`kg__flow${isMajor(e) ? ' kg__flow--major' : ''}`} style={{ animationDelay: `${(i % 5) * 0.2}s` }} />}
                  <path ref={reg} className="kg__hit" onClick={() => onSelect({ type: 'edge', id: e.id })}>
                    <title>{e.summary || e.label}</title>
                  </path>
                </g>
              );
            })}
          </g>
          <g>
            {visible.nodes.map((n) => {
              const k = KIND[n.kind];
              const sel = selection?.type === 'node' && selection.id === n.id;
              const d = nodeDelay(n);
              const label = n.kind === 'dose' || n.kind === 'dose_old' ? clip(n.short ?? n.label, 18) : n.label;
              return (
                <g
                  key={n.id}
                  ref={(el) => { if (el) nodeEls.current.set(n.id, el); else nodeEls.current.delete(n.id); }}
                  className={`kg__node${sel ? ' kg__node--selected' : ''}${hi.has(n.id) ? ' kg__node--hi' : ''}`}
                  style={{ ['--nc' as string]: k.color }}
                  role="button"
                  tabIndex={0}
                  aria-label={`${tr(k.word)}: ${n.label}. ${tr('Press Enter for details.')}`}
                  aria-pressed={sel}
                  onPointerDown={(e) => onNodeDown(e, n.id)}
                  onPointerMove={onNodeMove}
                  onPointerUp={onNodeUp}
                  onPointerEnter={() => setHover(n.id)}
                  onPointerLeave={() => setHover(null)}
                  onFocus={() => setHover(n.id)}
                  onBlur={() => setHover(null)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect({ type: 'node', id: n.id }); } }}
                >
                  <g className="kg__pop" style={{ ['--d' as string]: `${d}s` }}>
                    {major.has(n.id) && <circle className="kg__halo" r={k.r + 4} />}
                    <circle className="kg__sel" r={k.r + 6} />
                    {k.shape === 'circle' && <circle className="kg__body" r={k.r} />}
                    {k.shape === 'square' && <rect className="kg__body" x={-k.r} y={-k.r} width={k.r * 2} height={k.r * 2} rx={5} />}
                    {k.shape === 'capsule' && <rect className="kg__body" x={-k.r * 1.25} y={-k.r * 0.7} width={k.r * 2.5} height={k.r * 1.4} rx={k.r * 0.7} transform="rotate(-30)" />}
                    {k.shape === 'diamond' && <rect className="kg__body" x={-k.r * 0.8} y={-k.r * 0.8} width={k.r * 1.6} height={k.r * 1.6} rx={4} transform="rotate(45)" />}
                    <text className="kg__glyph">{glyphFor(n)}</text>
                    <text className="kg__label" y={k.r + 14}>{label}</text>
                  </g>
                </g>
              );
            })}
          </g>
        </g>
      </svg>
      <div className="kg__hint" aria-hidden="true">{tr('Click a node or line · drag · scroll to zoom')}</div>
      <div className="kg__ctl">
        <button type="button" aria-label="Zoom in" onClick={() => zoomBy(1.25)}><Plus size={18} aria-hidden="true" /></button>
        <button type="button" aria-label="Zoom out" onClick={() => zoomBy(1 / 1.25)}><Minus size={18} aria-hidden="true" /></button>
        <button type="button" aria-label="Fit to view" onClick={() => fit(true)}><Scan size={17} aria-hidden="true" /></button>
        <button type="button" aria-label={full ? 'Exit full screen' : 'Full screen'} onClick={toggleFull}>{full ? <Minimize2 size={17} aria-hidden="true" /> : <Expand size={17} aria-hidden="true" />}</button>
        <button type="button" aria-label="Pause motion" aria-pressed={still} onClick={() => setStill((s) => !s)}>{still ? <Play size={17} aria-hidden="true" /> : <Pause size={17} aria-hidden="true" />}</button>
      </div>
      <div className="kg__legend" aria-hidden="true">
        {kinds.map((k) => (
          <span key={k} style={{ ['--nc' as string]: KIND[k].color }}><i />{tr(KIND[k].word)}</span>
        ))}
      </div>
    </div>
  );
}
