import { describe, expect, it } from 'vitest';
import { translate } from './i18n';

/** Every plain-text string passed to tr() or t() in the source must have a Hindi form. A missing one would silently show English to a Hindi reader. */
const SOURCES = import.meta.glob(['../**/*.ts', '../**/*.tsx', '!../**/*.test.ts', '!../**/*.test.tsx'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>;

describe('Hindi coverage', () => {
  it('every literal tr("...") / t("...") string has a Hindi translation', () => {
    const missing: string[] = [];
    const re = /(?<![\w.$])(?:tr|t)\(\s*(['"])((?:\\.|(?!\1).)*)\1\s*[,)]/g;
    expect(Object.keys(SOURCES).length).toBeGreaterThan(20);
    let seen = 0;
    for (const [file, text] of Object.entries(SOURCES)) {
      for (const m of text.matchAll(re)) {
        const s = m[2].replace(/\\(['"])/g, '$1');
        if (!/[a-z]{2}/.test(s)) continue;                       // a code or a placeholder, not a sentence
        seen++;
        if (translate(s, 'hi') === s) missing.push(`${file}: ${s}`);
      }
    }
    expect(seen).toBeGreaterThan(100);                           // the pattern really finds the calls (it used to find only tr())
    expect(missing).toEqual([]);
  });

  it('no visible English sentence sits in the markup outside t()/tr()', () => {
    // JSX text between > and <, and the placeholder/title/aria-label/alt attributes, when they hold English words and are not an expression.
    const loose: string[] = [];
    const text = />\s*([A-Z][A-Za-z,'.’:\- ]{12,}[a-z.?!])\s*</g;
    const attr = /\b(?:placeholder|title|aria-label|alt)="([^"{}]*[A-Za-z]{3,}[^"{}]* [^"{}]*[A-Za-z]{2,}[^"{}]*)"/g;
    const ALLOW = /^(Care Circle|Amazon Cognito|FalkorDB|DDInter|openFDA|RxNorm|Telegram|WhatsApp|Web Push|FHIR|PageRank|Cypher|CYP)/;
    for (const [file, src] of Object.entries(SOURCES)) {
      if (/\/(api|graph|design)\//.test(file) || /hi_more|i18n\.tsx|cognito/.test(file)) continue;
      for (const m of src.matchAll(text)) if (!ALLOW.test(m[1]) && translate(m[1], 'hi') === m[1]) loose.push(`${file}: >${m[1]}<`);
      for (const m of src.matchAll(attr)) if (!ALLOW.test(m[1]) && translate(m[1], 'hi') === m[1]) loose.push(`${file}: ${m[0]}`);
    }
    expect(loose.join(' | ')).toEqual('');
  });
});
