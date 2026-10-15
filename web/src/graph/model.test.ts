import { describe, expect, it } from 'vitest';
import type { CareGraph, GraphEdge, GraphNode } from '../api/types';
import { ALL_LAYERS, clip, glyphFor, isFlagged, majorDrugs, neighbours, relationWord, visibleGraph, type Layer } from './model';

const n = (id: string, kind: GraphNode['kind'], label = id): GraphNode => ({ id, kind, label, summary: '', meta: [], cypher: '' });
const e = (source: string, target: string, kind: GraphEdge['kind'], level?: string): GraphEdge => ({ id: `${source}>${kind}>${target}`, source, target, kind, label: kind, summary: '', meta: [], level });

const g: CareGraph = {
  person: 'asha', now: 0, judgement: { state: 'flags', reasons: [], statement: '' }, legend: {}, notice: '',
  nodes: [n('person:asha', 'patient', 'Asha'), n('person:ravi', 'carer', 'Ravi'), n('dose:1', 'dose'), n('dose:0', 'dose_old'), n('drug:a', 'drug'), n('drug:b', 'drug'), n('enzyme:CYP3A', 'enzyme')],
  edges: [e('person:ravi', 'dose:1', 'recorded'), e('dose:1', 'drug:a', 'of'), e('dose:1', 'dose:0', 'supersedes'), e('drug:a', 'drug:b', 'interacts', 'major'), e('drug:a', 'enzyme:CYP3A', 'inhibits')],
};

describe('graph model', () => {
  it('keeps every layer by default', () => {
    const v = visibleGraph(g, new Set<Layer>(ALL_LAYERS));
    expect(v.nodes).toHaveLength(7);
    expect(v.edges).toHaveLength(5);
  });
  it('removes unchecked layers and any edge that lost an end', () => {
    const v = visibleGraph(g, new Set<Layer>(['entries']));
    expect(v.nodes.map((x) => x.id).sort()).toEqual(['dose:1', 'drug:a', 'drug:b', 'person:asha']);
    expect(v.edges.map((x) => x.kind)).toEqual(['of', 'interacts']);
  });
  it('lists neighbours with direction', () => {
    const ns = neighbours(g, 'drug:a');
    expect(ns.map((x) => `${x.node.id}:${x.outgoing}`).sort()).toEqual(['dose:1:false', 'drug:b:true', 'enzyme:CYP3A:true']);
    expect(relationWord(ns.find((x) => x.node.id === 'enzyme:CYP3A')!.edge, true)).toBe('slows');
  });
  it('knows which edges are flagged and which drugs sit on a major one', () => {
    expect(g.edges.filter(isFlagged).map((x) => x.kind)).toEqual(['interacts', 'inhibits']);
    expect([...majorDrugs(g.edges)].sort()).toEqual(['drug:a', 'drug:b']);
  });
  it('labels nodes without inventing text', () => {
    expect(glyphFor(n('p', 'patient', 'Asha'))).toBe('A');
    expect(glyphFor(n('d', 'dose'))).toBe('Rx');
    expect(clip('Clarithromycin 500 mg twice daily', 20)).toBe('Clarithromycin 500…');
  });
});
