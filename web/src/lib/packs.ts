import type { RegimenEntry, Unacknowledged } from '../api/types';
import { productName, title } from './format';

/** The record keeps one entry per ingredient (so each is checked and can be stopped on its own), but people hold PACKS: Telma-AM is one strip of two ingredients.
 *  These count and group by the pack, so "6 medicines" is not said for five packs and one new strip is not "two changes not seen". */
export const packKey = (e: { drug: string; product?: string }): string => (e.product ? `p:${e.product}` : `d:${e.drug}`);

export function countPacks(reg: RegimenEntry[]): number {
  return new Set(reg.map(packKey)).size;
}

export interface UnseenPack {
  key: string;
  /** Every entry to acknowledge for this pack. */
  ids: string[];
  /** What to call it: the product as printed, or the medicine. */
  label: string;
  ingredients: string[];
  action: string;
  age_hours: number;
}

/** Entries of one product, changed the same way, are one pack: they were typed from one prescription line. */
export function groupUnseen(list: Unacknowledged[]): UnseenPack[] {
  const out: UnseenPack[] = [];
  const by = new Map<string, UnseenPack>();
  for (const u of list) {
    const k = u.product ? `${u.product}|${u.action}` : '';
    const hit = k ? by.get(k) : undefined;
    if (hit) {
      hit.ids.push(u.dose);
      hit.ingredients.push(u.drug);
      hit.age_hours = Math.max(hit.age_hours, u.age_hours);
      continue;
    }
    const p: UnseenPack = { key: k || u.dose, ids: [u.dose], label: u.product ? productName(u.product) : title(u.drug), ingredients: [u.drug], action: u.action, age_hours: u.age_hours };
    out.push(p);
    if (k) by.set(k, p);
  }
  return out;
}
