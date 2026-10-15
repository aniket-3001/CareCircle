import { CirclePlus, History, ListChecks, Share2, Users } from 'lucide-react';
import { motion } from 'motion/react';

export type TabId = 'today' | 'add' | 'circle' | 'graph' | 'history';

const TABS = [
  { id: 'today', label: 'Today', Icon: ListChecks },
  { id: 'add', label: 'Add', Icon: CirclePlus },
  { id: 'circle', label: 'Circle', Icon: Users },
  { id: 'graph', label: 'Graph', Icon: Share2 },
  { id: 'history', label: 'History', Icon: History },
] as const;

/** The five places to go, in a floating pill at the bottom of the screen; the highlight slides between them. */
export function TabBar({ current, onSelect }: { current: TabId; onSelect: (t: TabId) => void }): React.JSX.Element {
  return (
    <nav className="tabbar" aria-label="Main">
      {TABS.map(({ id, label, Icon }) => (
        <button key={id} type="button" className="tab-link" aria-current={id === current ? 'page' : undefined} onClick={() => onSelect(id)}>
          {id === current && <motion.span layoutId="tab-pill" className="tab-pill" transition={{ type: 'spring', stiffness: 520, damping: 40 }} />}
          <Icon size={22} strokeWidth={1.75} aria-hidden="true" />
          <span>{label}</span>
        </button>
      ))}
    </nav>
  );
}
