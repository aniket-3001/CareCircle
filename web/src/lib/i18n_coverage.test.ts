import { describe, expect, it } from 'vitest';
import { translate } from './i18n';

/** Every plain-text string passed to tr() in the source must have a Hindi form. A missing one would silently show English to a Hindi reader. */
const SOURCES = import.meta.glob(['../**/*.ts', '../**/*.tsx', '!../**/*.test.ts', '!../**/*.test.tsx'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>;

describe('Hindi coverage', () => {
  it('every literal tr("...") string has a Hindi translation', () => {
    const missing: string[] = [];
    const re = /\btr\(\s*(['"])((?:\\.|(?!\1).)*)\1\s*[,)]/g;
    expect(Object.keys(SOURCES).length).toBeGreaterThan(20);
    for (const [file, text] of Object.entries(SOURCES)) {
      for (const m of text.matchAll(re)) {
        const s = m[2].replace(/\\(['"])/g, '$1');
        if (!/[a-z]{2}/.test(s)) continue;                       // a code or a placeholder, not a sentence
        if (translate(s, 'hi') === s) missing.push(`${file}: ${s}`);
      }
    }
    expect(missing).toEqual([]);
  });
});
