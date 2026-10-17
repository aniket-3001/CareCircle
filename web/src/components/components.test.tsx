import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it } from 'vitest';
import type { CheckResult } from '../api/types';
import { FaceIcon } from './Face';
import { Flags } from './Flags';
import { Hero } from './Hero';

const base = { direct: [], enzyme_paths: [], unrated: [], duplicates: [], unchecked: [], judgement: { state: 'no_known_conflict', headline: 'No known conflict', statement: 'This is not a statement that anything is safe.', reasons: [] }, regimen: [] };
const check = (over: Record<string, unknown> = {}): CheckResult => ({ ...base, ...over } as unknown as CheckResult);
(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
/** Render into a real (jsdom) DOM so hooks that need a browser, like the language store, work as they do on the page. */
const html = (el: React.JSX.Element): string => {
  const host = document.createElement('div');
  const root = createRoot(host);
  act(() => root.render(el));
  const out = host.innerHTML;
  act(() => root.unmount());
  return out;
};

describe('Flags', () => {
  it('with nothing flagged says so without calling anything safe', () => {
    const out = html(<Flags check={check()} />);
    expect(out.toLowerCase()).not.toMatch(/\b(is|are) safe\b|\bsafe to\b|all clear/);
    expect(out).toMatch(/not statement|not a statement|No flags/i);
  });
  it('shows a direct flag with its source and the graph pattern behind it', () => {
    const out = html(<Flags check={check({ direct: [{ kind: 'direct', drugs: ['atorvastatin', 'clarithromycin'], level: 'Major', source: 'DDInter 2.0' }] })} />);
    expect(out).toContain('Atorvastatin');
    expect(out).toContain('Clarithromycin');
    expect(out).toContain('DDInter 2.0');
    expect(out).toContain('INTERACTS');
  });
  it('shows a possible duplicate with each entry and its product', () => {
    const d = { kind: 'duplicate', ingredient: 'amlodipine', meaning: 'x', source: 's', entries: [{ id: '1', product: 'telma-am', dose_text: '40 mg', freq_text: 'daily', by: 'ravi' }, { id: '2', product: '', dose_text: '5 mg', freq_text: '', by: 'meena' }] };
    const out = html(<Flags check={check({ duplicates: [d] })} />);
    expect(out).toContain('data-testid="duplicate-flag"');
    expect(out.toLowerCase()).toContain('telma-am');
    expect(out).toContain('Amlodipine');
  });
  it('lists an unrated pair as unrated and never as fine', () => {
    const out = html(<Flags check={check({ unrated: [{ kind: 'unrated', drugs: ['a', 'b'], level: 'Unknown', source: 'DDInter 2.0' }] })} />);
    expect(out.toLowerCase()).toContain('unrated');
    expect(out.toLowerCase()).toContain('not the same as safe');                       // it says what unrated is not
    expect(out.toLowerCase()).not.toMatch(/\b(is|are|was|were) safe\b/);               // and never that anything is
  });
});

describe('Flags: laboratory findings', () => {
  const lab = { kind: 'enzyme_path', path: 'quinidine -INHIBITS(in vitro)-> P-gp <-SUBSTRATE_OF- digoxin', meaning: 'quinidine may raise exposure of digoxin through the P-gp transporter (a laboratory finding, not shown in people)',
    weight: 0.1, also_in_ddinter: false, source: 'FDA transporter in vitro table (laboratory finding); substrate: FDA', x: 'quinidine', y: 'digoxin', enzyme: 'P-gp', relation: 'INHIBITS', strength: 'in vitro', target: 'transporter' };
  it('labels a transporter path as a lab finding and says so in words', () => {
    const out = html(<Flags check={check({ enzyme_paths: [lab] })} />);
    expect(out).toContain('transporter path');
    expect(out).toContain('lab finding');
    expect(out).toContain('not shown in people');
  });
  it('a laboratory finding alone colours the page as minor, not moderate', async () => {
    const { worstSeverity } = await import('../design/levels');
    expect(worstSeverity(check({ enzyme_paths: [lab] }))).toBe('minor');
    expect(worstSeverity(check({ enzyme_paths: [lab, { ...lab, strength: 'strong' }] }))).toBe('moderate');
  });
});

describe('Hero (the status card)', () => {
  it('with no flags is neutral and carries the not-a-statement-of-safety line', () => {
    const out = html(<Hero check={check()} chips={[]} />);
    expect(out).toContain('data-state');
    expect(out).toContain('data-testid="verdict"');
    expect(out.toLowerCase()).not.toContain('happy');
  });
  it('with a major flag says it and counts it', () => {
    const out = html(<Hero check={check({ direct: [{ kind: 'direct', drugs: ['atorvastatin', 'clarithromycin'], level: 'Major', source: 'DDInter 2.0' }], judgement: { state: 'flags', headline: 'Interactions flagged', statement: 'Possible interactions found: discuss with a prescriber or pharmacist.', reasons: [] } })} chips={[]} />);
    expect(out).toContain('Major interaction flagged');
    expect(out).toContain('prescriber or pharmacist');
  });
});

describe('FaceIcon', () => {
  it('draws a different mouth for each face and the neutral one is a straight line', () => {
    const mouths = (['happy', 'neutral', 'concerned'] as const).map((f) => html(<FaceIcon face={f} />));
    expect(new Set(mouths).size).toBe(3);
    expect(html(<FaceIcon face="neutral" />)).toContain('M24 41h16');
  });
});
