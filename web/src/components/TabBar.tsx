export type TabId = 'today' | 'add' | 'circle' | 'graph' | 'history';

const TABS: readonly { id: TabId; label: string; path: string }[] = [
  { id: 'today', label: 'Today', path: 'M4 6h16M4 12h16M4 18h10' },
  { id: 'add', label: 'Add', path: 'M12 5v14M5 12h14' },
  { id: 'circle', label: 'Circle', path: 'M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7 0a2.5 2.5 0 1 0 0-5M3 20c0-3 2.7-5 6-5s6 2 6 5m1-5c2.8 0 5 1.8 5 5' },
  { id: 'graph', label: 'Graph', path: 'M6 7a2 2 0 1 0 0-4 2 2 0 0 0 0 4Zm12 5a2 2 0 1 0 0-4 2 2 0 0 0 0 4ZM9 21a2 2 0 1 0 0-4 2 2 0 0 0 0 4ZM7.7 6.2l8.6 3.6M7 7l1.5 10' },
  { id: 'history', label: 'History', path: 'M12 7v5l3 2M3 12a9 9 0 1 0 3-6.7M3 4v4h4' },
];

/** The five places to go, always in reach (Vayu's tab bar). */
export function TabBar({ current, onSelect }: { current: TabId; onSelect: (t: TabId) => void }): React.JSX.Element {
  return (
    <nav className="tabbar" aria-label="Primary">
      {TABS.map((t) => (
        <button key={t.id} type="button" className="tabbar__item" aria-current={t.id === current ? 'page' : undefined} onClick={() => onSelect(t.id)}>
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
            <path d={t.path} />
          </svg>
          <span>{t.label}</span>
        </button>
      ))}
    </nav>
  );
}
