import type { Session } from '../api/types';

const KEY = 'cc-session-v3';

/** The only thing kept in the browser: a bearer token (and which circle is open). Everything else is read from the server on every load. */
export function loadSession(): Session | null {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as Session;
    return s.keys && Object.keys(s.keys).length && typeof s.circle === 'string' ? s : null;
  } catch {
    return null;
  }
}

export function saveSession(s: Session | null): void {
  try {
    if (s) window.localStorage.setItem(KEY, JSON.stringify(s));
    else window.localStorage.removeItem(KEY);
    window.localStorage.removeItem('cc-session-v2');
  } catch {
    /* private mode: the app still works for this visit */
  }
}
