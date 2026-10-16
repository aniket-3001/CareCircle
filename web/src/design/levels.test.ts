import { describe, expect, it } from 'vitest';
import { SEVERITY, worstSeverity } from './levels';
import type { CheckResult } from '../api/types';

const check = (over: Partial<CheckResult>): CheckResult => ({
  direct: [], enzyme_paths: [], unrated: [], judgement: { state: 'no_known_conflict', statement: '', reasons: [] }, ...over,
} as unknown as CheckResult);

describe('what the status card shows when nothing is flagged', () => {
  it('is grey and not smiling: no flag is not a statement of safety', () => {
    expect(worstSeverity(check({}))).toBe('none');
    expect(SEVERITY.none.face).toBe('neutral');
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(SEVERITY.none.solid.slice(i, i + 2), 16));
    expect(g > r + 20 && g > b + 20).toBe(false);          // no green cast
  });
  it('no part of the severity scale smiles', () => {
    expect(Object.values(SEVERITY).map((s) => s.face)).not.toContain('happy');
  });
});
