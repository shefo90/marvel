import { useCart } from '../../../hooks/useCart.jsx';
import { useLocale } from '../../../hooks/useLocale.jsx';
import { usePageContext } from '../../../hooks/usePageContext.jsx';
import { LOCALE_CODES, localeOf } from '../../../utils/locales.js';
import styles from './Header.module.scss';

const COPY = {
  en: { shop: 'Shop', cart: 'Cart', brand: 'Marvel', menu: 'Categories', all: 'View all' },
  ar: {
    shop: 'المتجر', cart: 'السلة', brand: 'مارفل', menu: 'الأقسام',
    all: 'عرض الكل',
  },
};

/**
 * The language switch is a link, not a control.
 *
 * It changes the URL, and the URL is the only thing that decides language.
 * A JavaScript toggle that swapped content in place would leave two languages
 * at one address, which is the duplicate-content problem section 8A exists to
 * prevent — and would be invisible to a crawler.
 *
 * The category menu is rendered as real nested links, open on hover *and* on
 * focus, with no JavaScript deciding what is visible. That is what makes it
 * crawlable: a menu built from state renders empty in the initial HTML, so the
 * whole category tree would be invisible to the crawler that most needs it.
 */
export default function Header() {
  const { locale, href, switchTo } = useLocale();
  const { itemCount } = useCart();
  const pageContext = usePageContext();
  const copy = COPY[locale] ?? COPY.en;

  // Supplied by each page's +data. Absent on a page that did not load it, in
  // which case the shop still works — it just navigates from the footer.
  const categories = pageContext?.data?.categories ?? [];

  return (
    <header className={styles.header}>
      <div className={styles.bar}>
        <a className={styles.brand} href={href('/')}>
          {copy.brand}
        </a>

        <nav className={styles.nav} aria-label={copy.menu}>
          <ul className={styles.topLevel}>
            {categories.map((category) => (
              <li key={category.id} className={styles.topItem}>
                <a className={styles.topLink} href={href(`/c/${category.slug}`)}>
                  {category.title}
                </a>

                {category.children?.length ? (
                  <div className={styles.panel}>
                    <ul className={styles.children}>
                      {category.children.map((child) => (
                        <li key={child.id}>
                          <a href={href(`/c/${child.slug}`)}>{child.title}</a>
                        </li>
                      ))}
                      <li>
                        <a
                          className={styles.viewAll}
                          href={href(`/c/${category.slug}`)}
                        >
                          {copy.all}
                        </a>
                      </li>
                    </ul>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
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
      </div>
    </header>
  );
}
