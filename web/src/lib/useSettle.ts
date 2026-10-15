import { animate, useReducedMotion } from 'motion/react';
import { useEffect, useRef, useState } from 'react';

/** A number that settles to its value over 600 ms, from wherever it was. Instant when motion is reduced (as in The Vayu Project). */
export function useSettle(target: number): number {
  const reduced = useReducedMotion() === true;
  const [shown, setShown] = useState(reduced ? target : 0);
  const from = useRef(reduced ? target : 0);
  useEffect(() => {
    if (reduced) {
      setShown(target);
      from.current = target;
      return;
    }
    const controls = animate(from.current, target, {
      duration: 0.6,
      ease: 'easeOut',
      onUpdate: (v) => {
        from.current = v;
        setShown(Math.round(v));
      },
    });
    return () => controls.stop();
  }, [target, reduced]);
  return shown;
}
