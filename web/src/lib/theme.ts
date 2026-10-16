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

export type TextSize = 'normal' | 'large' | 'larger';
const SIZE_KEY = 'cc-text';
const sizeListeners = new Set<() => void>();

export function currentTextSize(): TextSize {
  try {
    const v = window.localStorage.getItem(SIZE_KEY);
    return v === 'large' || v === 'larger' ? v : 'normal';
  } catch {
    return 'normal';
  }
}

export function applyTextSize(s: TextSize): void {
  document.documentElement.dataset.text = s;
}

export function setTextSize(s: TextSize): void {
  try {
    window.localStorage.setItem(SIZE_KEY, s);
  } catch {
    /* private window: lasts until the page closes */
  }
  applyTextSize(s);
  sizeListeners.forEach((l) => l());
}

export function useTextSize(): TextSize {
  return useSyncExternalStore(
    (cb) => { sizeListeners.add(cb); return () => sizeListeners.delete(cb); },
    () => (document.documentElement.dataset.text === 'large' || document.documentElement.dataset.text === 'larger' ? (document.documentElement.dataset.text as TextSize) : 'normal'),
  );
}
