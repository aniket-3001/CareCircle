const HOUR = 3_600_000;

/** 'vitamin d' -> 'Vitamin D', 'vitamin b12' -> 'Vitamin B12': the first letter is capitalised, and so is a lone letter (with digits) that names a vitamin. */
export const title = (s: string): string =>
  s ? (s.charAt(0).toUpperCase() + s.slice(1)).replace(/(?<=\bvitamin )[a-z]\d*\b/gi, (m) => m.toUpperCase()) : s;

/** 'ravi-455d702e' -> 'Ravi' (demo agents carry a circle suffix). */
export const nameOf = (agent: string): string => title((agent || '').split('-')[0] ?? '');

export function ago(ms: number, now: number): string {
  const h = (now - ms) / HOUR;
  if (h < 0.05) return 'just now';
  if (h < 1) return `${Math.round(h * 60)} min ago`;
  if (h < 48) return `${h.toFixed(h < 10 ? 1 : 0).replace(/\.0$/, '')} h ago`;
  return `${Math.round(h / 24)} days ago`;
}

export function when(ms: number): string {
  return new Date(ms).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export const plural = (n: number, one: string, many = `${one}s`): string => `${n} ${n === 1 ? one : many}`;

export const pct = (x: number): string => `${Math.round(x * 100)}%`;
