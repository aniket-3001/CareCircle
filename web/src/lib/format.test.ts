import { describe, expect, it } from 'vitest';
import { ago, nameOf, pct, plural, title } from './format';

describe('format', () => {
  it('names agents without their circle suffix', () => {
    expect(nameOf('ravi-455d702e')).toBe('Ravi');
    expect(nameOf('')).toBe('');
  });
  it('says how long ago in plain words', () => {
    const now = 100 * 3_600_000;
    expect(ago(now - 60_000 * 20, now)).toBe('20 min ago');
    expect(ago(now - 5.4 * 3_600_000, now)).toBe('5.4 h ago');
    expect(ago(now - 3 * 24 * 3_600_000, now)).toBe('3 days ago');
    expect(ago(now, now)).toBe('just now');
  });
  it('title-cases and pluralises', () => {
    expect(title('clarithromycin')).toBe('Clarithromycin');
    expect(plural(1, 'change')).toBe('1 change');
    expect(plural(2, 'change')).toBe('2 changes');
    expect(pct(0.904)).toBe('90%');
  });
});
