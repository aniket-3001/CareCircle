import type { CheckResult } from '../api/types';

/** The darkest colour we use: a greyed slate, not navy or black (as in The Vayu Project). */
export const INK = '#334155';

export type Face = 'happy' | 'neutral' | 'concerned';

export interface Level {
  readonly name: string;
  /** The strong colour: the status card and chips. */
  readonly solid: string;
  readonly onSolid: string;
  /** A faint tint of the same colour. */
  readonly soft: string;
  readonly face: Face;
}

/** The AQI levels in IQAir's softer colours, reused as the severity of what the record says. Text on them is ink, never white. */
export const SEVERITY = {
  none: { name: 'No flag', solid: '#dbe3ec', onSolid: INK, soft: '#eef2f7', face: 'neutral' },      // grey, not green and not smiling: no flag is not a statement of safety
  minor: { name: 'Minor', solid: '#f7d65c', onSolid: INK, soft: '#fdf6d9', face: 'neutral' },
  moderate: { name: 'Moderate', solid: '#f7b56b', onSolid: INK, soft: '#fdebd6', face: 'concerned' },
  major: { name: 'Major', solid: '#f39595', onSolid: INK, soft: '#fde4e4', face: 'concerned' },
  unrated: { name: 'Unrated', solid: '#cfd8e3', onSolid: INK, soft: '#eef2f7', face: 'neutral' },
} as const satisfies Record<string, Level>;
export type SeverityKey = keyof typeof SEVERITY;

/** The most serious thing the record flags, for the colour of the page. */
export function worstSeverity(c: CheckResult): SeverityKey {
  const levels = c.direct.map((f) => f.level.toLowerCase());
  if (levels.includes('major')) return 'major';
  if (levels.includes('moderate') || c.enzyme_paths.length > 0) return 'moderate';
  if (levels.includes('minor')) return 'minor';
  if (c.unrated.length > 0 || c.judgement.state === 'partial') return 'unrated';
  return c.judgement.state === 'no_known_conflict' ? 'none' : 'unrated';
}

export const sevKey = (level: string): SeverityKey => {
  const l = level.toLowerCase();
  return l === 'major' || l === 'moderate' || l === 'minor' ? l : 'unrated';
};

/** CSS variables that colour a card or the page with a severity. */
export const levelVars = (k: SeverityKey): Record<string, string> => ({
  ['--level' as string]: SEVERITY[k].solid,
  ['--on-level' as string]: SEVERITY[k].onSolid,
});
