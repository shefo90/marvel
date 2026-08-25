import { money, priceParts } from '../../../utils/format.js';
import { useLocale } from '../../../hooks/useLocale.jsx';
import styles from './Price.module.scss';

/**
 * A price, and the price it used to be.
 *
 * The struck-through number is wrapped in <s> rather than styled with CSS
 * alone, so a screen reader announces it as no longer current instead of
 * reading two prices with no relationship between them.
 */
export default function Price({ price, salePrice }) {
  const { locale } = useLocale();
  const { now, was, hasMarkdown } = priceParts(price, salePrice);

  return (
    <span className={styles.price}>
      <span className={hasMarkdown ? styles.now : undefined}>{money(now, locale)}</span>
      {was ? <s className={styles.was}>{money(was, locale)}</s> : null}
    </span>
  );
}
