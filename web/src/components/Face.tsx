import type { Face as FaceName } from '../design/levels';

const BROWS: Partial<Record<FaceName, string>> = { concerned: 'M17 19.5l8-1.5M47 19.5l-8-1.5' };
const MOUTHS: Record<FaceName, string> = { happy: 'M21 38c3 6 19 6 22 0', neutral: 'M24 41h16', concerned: 'M23 44c3-5 15-5 18 0' };

/** The status face, drawn in one stroke colour so it takes the card's ink (from The Vayu Project's icons). */
export function FaceIcon({ face, size = 72 }: { face: FaceName; size?: number }): React.JSX.Element {
  const brows = BROWS[face];
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="face">
      <circle cx="32" cy="32" r="28" />
      {brows && <path d={brows} strokeWidth="2.75" />}
      <circle cx="23" cy="27" r="2.6" fill="currentColor" stroke="none" />
      <circle cx="41" cy="27" r="2.6" fill="currentColor" stroke="none" />
      <path d={MOUTHS[face]} />
    </svg>
  );
}
