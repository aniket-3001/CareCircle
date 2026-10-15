import { useSyncExternalStore } from 'react';

export type Theme = 'light' | 'dark';
const KEY = 'cc-theme';
const listeners = new Set<() => void>();

function stored(): Theme | null {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === 'dark' || v === 'light' ? v : null;
  } catch {
    return null;
  }
}

/** The person's choice if they made one, else what the device prefers. */
export function currentTheme(): Theme {
  return stored() ?? (window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
}

export function applyTheme(t: Theme): void {
  document.documentElement.dataset.theme = t;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', t === 'dark' ? '#0f151d' : '#f4f7fb');
  document.querySelector('meta[name="color-scheme"]')?.setAttribute('content', t);
}

export function setTheme(t: Theme): void {
  try {
    window.localStorage.setItem(KEY, t);
  } catch {
    /* private window: the choice lasts until the page closes */
  }
  applyTheme(t);
  listeners.forEach((l) => l());
}

export function useTheme(): Theme {
  return useSyncExternalStore(
    (cb) => { listeners.add(cb); return () => listeners.delete(cb); },
    () => (document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'),
  );
}
