import { describe, expect, it } from 'vitest';
import { translate } from './i18n';

/** Every sentence the Graph tab's "Ask the graph" card and its warnings show must have a Hindi form; a missing key would silently show English. */
const SENTENCES = [
  'These rankings describe how the records are connected in this graph. They say nothing about which medicine matters medically.',
  'What the record hangs on',
  'What belongs together',
  'How are two records connected?',
  'Reach',
  'Bridges',
  'Computed exactly by this server from the links stored in FalkorDB.',
  'records are not linked to anything here, so these rankings are shallow.',
  'Find the path',
];

describe('Hindi for the Graph tab', () => {
  it('has a Hindi form, different from the English, for each sentence', () => {
    for (const s of SENTENCES) {
      const hi = translate(s, 'hi');
      expect(hi, s).not.toBe(s);
      expect(/[ऀ-ॿ]/.test(hi), s).toBe(true);        // Devanagari
      expect(translate(s, 'en')).toBe(s);
    }
  });
});
