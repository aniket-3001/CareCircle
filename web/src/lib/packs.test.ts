import { describe, expect, it } from 'vitest';
import type { RegimenEntry, Unacknowledged } from '../api/types';
import { countPacks, groupUnseen } from './packs';

const e = (drug: string, product = ''): RegimenEntry => ({ id: drug + product, drug, product, dose_text: '', freq_text: '', since: 0, source: 'typed', quote: '', by: 'a' } as unknown as RegimenEntry);
const u = (drug: string, product = '', action = 'set', age = 1): Unacknowledged => ({ dose: `${drug}-${product}`, drug, action, age_hours: age, product });

describe('packs, not molecules', () => {
  it('counts a combination as one medicine', () => {
    expect(countPacks([e('telmisartan', 'telma-am'), e('amlodipine', 'telma-am'), e('metformin'), e('atorvastatin'), e('vitamin d')])).toBe(4);
    expect(countPacks([e('atorvastatin', 'storvas'), e('atorvastatin', 'atorva')])).toBe(2);        // two brands of one molecule are two packs
    expect(countPacks([])).toBe(0);
  });
  it('groups one strip into one unseen change and keeps every id to acknowledge', () => {
    const g = groupUnseen([u('telmisartan', 'telma-am'), u('amlodipine', 'telma-am', 'set', 3), u('metformin')]);
    expect(g).toHaveLength(2);
    expect(g[0]).toMatchObject({ label: 'Telma-AM', ingredients: ['telmisartan', 'amlodipine'], age_hours: 3 });
    expect(g[0]?.ids).toHaveLength(2);
    expect(g[1]).toMatchObject({ label: 'Metformin', ids: ['metformin-'] });
  });
  it('does not merge a stop with a change', () => {
    expect(groupUnseen([u('telmisartan', 'telma-am', 'stop'), u('amlodipine', 'telma-am', 'set')])).toHaveLength(2);
  });
});
