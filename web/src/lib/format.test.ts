import { describe, expect, it } from 'vitest';
import { ago, nameOf, pct, plural, productName, shown, title, whenLocal } from './format';

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
  it('writes vitamin letters as capitals', () => {
    expect(title('vitamin d')).toBe('Vitamin D');
    expect(title('vitamin b12')).toBe('Vitamin B12');
    expect(title('vitamin d3 with calcium')).toBe('Vitamin D3 with calcium');
    expect(title('vitamins')).toBe('Vitamins');
    expect(title('')).toBe('');
  });
});

describe('whenLocal', () => {
  it('names the viewer zone and never says UTC unless that is the zone', () => {
    const s = whenLocal(Date.UTC(2026, 9, 16, 16, 56));
    expect(s).toMatch(/16 Oct|Oct 16/);
    expect(s.length).toBeGreaterThan(8);
  });
});

it('shows a combination product as it is printed, and a row by its product when it has one', () => {
  expect(productName('telma-am')).toBe('Telma-AM');
  expect(productName('glycomet-gp')).toBe('Glycomet-GP');
  expect(productName('ecosprin gold')).toBe('Ecosprin Gold');
  expect(shown({ drug: 'amlodipine', label: 'telma-am' })).toBe('Telma-AM');
  expect(shown({ drug: 'vitamin d' })).toBe('Vitamin D');
  expect(plural(1, 'flag')).toBe('1 flag');
  expect(plural(2, 'flag')).toBe('2 flags');
});
