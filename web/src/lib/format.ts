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

/** The viewer's own local date and time, with the zone named ("16 Oct, 10:26 pm IST"): a family in India should not read UTC. */
export function whenLocal(ms: number): string {
  const d = new Date(ms);
  const zone = new Intl.DateTimeFormat(undefined, { timeZoneName: 'short' }).formatToParts(d).find((p) => p.type === 'timeZoneName')?.value ?? '';
  return `${d.toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })} ${zone}`.trim();
}

export const plural = (n: number, one: string, many = `${one}s`): string => `${n} ${n === 1 ? one : many}`;

export const pct = (x: number): string => `${Math.round(x * 100)}%`;

/** A combination product's name for display: stored lower-case ("telma-am"), shown as it is usually printed ("Telma-AM"): short parts after a hyphen in capitals. */
export function productName(p: string): string {
  return p.split(' ').map((w) => w.split('-').map((x, i) => (i > 0 && x.length <= 3 ? x.toUpperCase() : x.charAt(0).toUpperCase() + x.slice(1))).join('-')).join(' ');
}

/** What a checklist row is called: the product when it is a combination (one tablet), else the medicine. */
export function shown(x: { drug: string; label?: string }): string {
  return x.label ? productName(x.label) : title(x.drug);
}
