import type { CareGraph, EdgeKind, GraphEdge, GraphNode, NodeKind } from '../api/types';

export type Layer = 'people' | 'entries' | 'history' | 'enzymes';
export const ALL_LAYERS: Layer[] = ['people', 'entries', 'history', 'enzymes'];
export const LAYER_LABEL: Record<Layer, string> = { people: 'People', entries: 'Entries', history: 'History', enzymes: 'Enzymes' };

export interface KindStyle {
  color: string;
  r: number;
  glyph: string;
  shape: 'circle' | 'square' | 'capsule' | 'diamond';
  word: string; // what to call it in a sentence
  ring: number; // preferred orbit, as a fraction of the available radius (0 = centre)
  order: number; // entrance order
}

export const KIND: Record<NodeKind, KindStyle> = {
  patient: { color: 'var(--c-patient)', r: 27, glyph: '', shape: 'circle', word: 'person cared for', ring: 0, order: 0 },
  carer: { color: 'var(--c-carer)', r: 20, glyph: '', shape: 'circle', word: 'carer', ring: 0.97, order: 1 },
  dose: { color: 'var(--c-dose)', r: 13, glyph: 'Rx', shape: 'square', word: 'current entry', ring: 0.34, order: 2 },
  dose_old: { color: 'var(--c-dose-old)', r: 11, glyph: 'Rx', shape: 'square', word: 'past entry', ring: 0.47, order: 3 },
  drug: { color: 'var(--c-drug)', r: 17, glyph: '', shape: 'capsule', word: 'medicine', ring: 0.64, order: 4 },
  drug_old: { color: 'var(--c-dose-old)', r: 14, glyph: '', shape: 'capsule', word: 'past medicine', ring: 0.78, order: 5 },
  enzyme: { color: 'var(--c-enzyme)', r: 15, glyph: 'E', shape: 'diamond', word: 'liver enzyme', ring: 0.97, order: 6 },
  product: { color: 'var(--c-product)', r: 15, glyph: 'Tab', shape: 'capsule', word: 'tablet or brand', ring: 0.5, order: 3 },
};

const LAYER_OF: Record<NodeKind, Layer | null> = { patient: null, carer: 'people', dose: 'entries', dose_old: 'history', drug: null, drug_old: 'history', enzyme: 'enzymes', product: 'entries' };

export interface Visible {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

/** The graph with unchecked layers removed (and any edge that lost an end). */
export function visibleGraph(g: CareGraph, layers: ReadonlySet<Layer>): Visible {
  const nodes = g.nodes.filter((n) => {
    const l = LAYER_OF[n.kind];
    return l === null || layers.has(l);
  });
  const ids = new Set(nodes.map((n) => n.id));
  return { nodes, edges: g.edges.filter((e) => ids.has(e.source) && ids.has(e.target)) };
}

export interface Neighbour {
  node: GraphNode;
  edge: GraphEdge;
  outgoing: boolean;
}

export function neighbours(g: Visible | CareGraph, id: string): Neighbour[] {
  const byId = new Map(g.nodes.map((n) => [n.id, n]));
  const out: Neighbour[] = [];
  for (const e of g.edges) {
    if (e.source === id && byId.has(e.target)) out.push({ node: byId.get(e.target)!, edge: e, outgoing: true });
    else if (e.target === id && byId.has(e.source)) out.push({ node: byId.get(e.source)!, edge: e, outgoing: false });
  }
  return out;
}

const VERB: Record<EdgeKind, [string, string]> = {
  for: ['is for', 'has the entry'],
  of: ['is for the medicine', 'has the entry'],
  recorded: ['recorded', 'was recorded by'],
  acked: ['acknowledged', 'was acknowledged by'],
  supersedes: ['replaced', 'was replaced by'],
  interacts: ['is listed as interacting with', 'is listed as interacting with'],
  inhibits: ['slows', 'is slowed by'],
  induces: ['speeds up', 'is sped up by'],
  substrate: ['is cleared by', 'clears'],
  via: ['is the tablet', 'has the entry'],
  contains: ['contains', 'is contained in'],
};
export const relationWord = (e: GraphEdge, outgoing: boolean): string => VERB[e.kind][outgoing ? 0 : 1];

/** Edges worth animating: the ones that mean something is flagged. */
export const isFlagged = (e: GraphEdge): boolean => e.kind === 'interacts' ? e.level === 'major' || e.level === 'moderate' : e.kind === 'inhibits' || e.kind === 'induces';
export const isMajor = (e: GraphEdge): boolean => e.kind === 'interacts' && e.level === 'major';

export function edgeClass(e: GraphEdge): string {
  const lvl = e.kind === 'interacts' ? ` kg__edge--${e.level ?? 'unknown'}` : '';
  return `kg__edge kg__edge--${e.kind}${lvl}`;
}

/** Drugs that sit on a major interaction pulse. */
export function majorDrugs(edges: GraphEdge[]): Set<string> {
  const s = new Set<string>();
  for (const e of edges) if (isMajor(e)) { s.add(e.source); s.add(e.target); }
  return s;
}

export const clip = (s: string, n = 20): string => (s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s);

export function glyphFor(n: GraphNode): string {
  const k = KIND[n.kind];
  return k.glyph || n.label.charAt(0).toUpperCase();
}
