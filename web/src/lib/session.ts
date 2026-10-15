import type { Session } from '../api/types';

const KEY = 'cc-session-v2';

export function loadSession(): Session | null {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as Session;
    return s.circle && s.keys && Object.keys(s.keys).length ? s : null;
  } catch {
    return null;
  }
}

export function saveSession(s: Session | null): void {
  try {
    if (s) window.localStorage.setItem(KEY, JSON.stringify(s));
    else window.localStorage.removeItem(KEY);
  } catch {
    /* private mode: the app still works for this visit */
  }
}
