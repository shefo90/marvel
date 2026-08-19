import { useEffect, useRef, useState } from 'react';

import styles from './ProductImage.module.scss';

/**
 * True when this <img> has already finished and has no pixels.
 *
 * Exported because it is the whole subtlety of this component: on a
 * server-rendered page the browser starts (and fails) the request before React
 * hydrates, so the ``error`` event has already been and gone by the time an
 * onError handler exists. A handler alone therefore works in development, on
 * client-side navigation, and never on a cold load — which is the load that
 * matters.
 */
export function alreadyFailed(img) {
  return Boolean(img) && img.complete && img.naturalWidth === 0;
}

/**
 * A product photograph, with a graceful failure.
 *
 * ``width`` and ``height`` are always passed through, because they are what
 * hold CLS under 0.1 — section 8A treats a missing dimension as a layout-shift
 * bug, and ``product_images`` makes both columns NOT NULL so this can rely on
 * them.
 *
 * When the file does not load — a moved CDN, a half-migrated catalogue — the
 * frame keeps its size and shows a neutral pattern. A browser's broken-image
 * icon across a product grid makes a working shop look broken.
 */
export default function ProductImage({ image, eager = false, priority = false, className }) {
  const [failed, setFailed] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (alreadyFailed(ref.current)) setFailed(true);
  }, [image?.url]);

  if (!image || failed) {
    return <div className={`${styles.placeholder} ${className ?? ''}`} aria-hidden="true" />;
  }

  return (
    <img
      ref={ref}
      src={image.url}
      alt={image.alt_text}
      width={image.width}
      height={image.height}
      loading={eager ? 'eager' : 'lazy'}
      fetchPriority={priority ? 'high' : undefined}
      // Both paths are needed: this one for a failure after hydration, the
      // effect above for one that happened before it.
      onError={() => setFailed(true)}
      className={className}
    />
  );
}
