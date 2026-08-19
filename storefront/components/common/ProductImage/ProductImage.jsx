import { useState } from 'react';

import styles from './ProductImage.module.scss';

/**
 * A product photograph, with a graceful failure.
 *
 * ``width`` and ``height`` are always passed through, because they are what
 * hold CLS under 0.1 — section 8A treats a missing dimension as a layout-shift
 * bug, and ``product_images`` makes both columns NOT NULL so this can rely on
 * them.
 *
 * When the file does not load — a moved CDN, a half-migrated catalogue — the
 * frame stays exactly the same size and shows nothing. A browser's broken-image
 * icon in a product grid makes a working shop look broken, and the reserved
 * space means the failure does not shift the page either.
 */
export default function ProductImage({ image, eager = false, priority = false, className }) {
  const [failed, setFailed] = useState(false);

  if (!image || failed) {
    return <div className={`${styles.placeholder} ${className ?? ''}`} aria-hidden="true" />;
  }

  return (
    <img
      src={image.url}
      alt={image.alt_text}
      width={image.width}
      height={image.height}
      loading={eager ? 'eager' : 'lazy'}
      fetchPriority={priority ? 'high' : undefined}
      onError={() => setFailed(true)}
      className={className}
    />
  );
}
