import { useEffect, useState } from 'react';

/**
 * Settle a fast-changing value before anything acts on it.
 *
 * The search box needs this for a reason beyond request count: four keystrokes
 * are four listings racing each other, and the earliest response can arrive
 * last and win. Debouncing means there is only ever one answer in flight.
 */
export function useDebounce(value, delay = 300) {
  const [settled, setSettled] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return settled;
}
