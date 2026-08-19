import { useCart } from '../../../hooks/useCart.jsx';
import { useLocale } from '../../../hooks/useLocale.jsx';
import { LOCALE_CODES, localeOf } from '../../../utils/locales.js';
import styles from './Header.module.scss';

const COPY = {
  en: { shop: 'Shop', cart: 'Cart', brand: 'Marvel' },
  ar: { shop: 'المتجر', cart: 'السلة', brand: 'مارفل' },
};

/**
 * The language switch is a link, not a control.
 *
 * It changes the URL, and the URL is the only thing that decides language.
 * A JavaScript toggle that swapped content in place would leave two languages
 * at one address, which is the duplicate-content problem section 8A exists to
 * prevent — and would be invisible to a crawler.
 */
export default function Header() {
  const { locale, href, switchTo } = useLocale();
  const { itemCount } = useCart();
  const copy = COPY[locale] ?? COPY.en;

  return (
    <header className={styles.header}>
      <a className={styles.brand} href={href('/')}>
        {copy.brand}
      </a>

      <nav className={styles.nav} aria-label={copy.shop}>
        <a href={href('/')}>{copy.shop}</a>
      </nav>

      <div className={styles.tail}>
        <ul className={styles.languages}>
          {LOCALE_CODES.map((code) => (
            <li key={code}>
              {code === locale ? (
                <span aria-current="true" className={styles.currentLanguage}>
                  {localeOf(code).native}
                </span>
              ) : (
                /* rel=external keeps Vike's client router out of this link,
                   so switching language is a FULL navigation and the server
                   re-renders <html lang/dir>. Section 6.7 requires exactly
                   that: never an in-page re-render or a runtime RTL pass. */
                <a href={switchTo(code)} hrefLang={code} rel="external">
                  {localeOf(code).native}
                </a>
              )}
            </li>
          ))}
        </ul>

        <a className={styles.cart} href={href('/cart')}>
          {copy.cart}
          {itemCount > 0 ? <span className={styles.count}>{itemCount}</span> : null}
        </a>
      </div>
    </header>
  );
}
