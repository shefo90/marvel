import { useEffect, useRef } from 'react';

import { pushEvent } from '../services/dataLayer.js';

/**
 * Fire one measurement event once, after the page has rendered.
 *
 * The ref matters. React re-renders for reasons that have nothing to do with
 * navigation -- a cart loading, a size being picked -- and a view_item that
 * fires on each of them inflates every view count without anyone noticing.
 * The key is what identifies "the same page view".
 */
export function useTrackOnce(key, build) {
  const lastKey = useRef(null);

  useEffect(() => {
    if (key == null || lastKey.current === key) return;
    lastKey.current = key;
    const payload = build();
    if (payload) pushEvent(payload);
    // `build` is deliberately not a dependency: it is rebuilt on every render
    // and including it would defeat the whole point.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
}
