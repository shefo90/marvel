import { useCart } from '../../../hooks/useCart.jsx';
import { useLocale } from '../../../hooks/useLocale.jsx';
import { usePageContext } from '../../../hooks/usePageContext.jsx';
import { LOCALE_CODES, localeOf } from '../../../utils/locales.js';
import styles from './Header.module.scss';

const COPY = {
  en: {
    shop: 'Shop',
    cart: 'Cart',
    account: 'Your account',
    brand: 'Marvel',
    menu: 'Categories',
    all: 'View all',
    announce: 'Cash on delivery · Nationwide delivery across Egypt',
    edits: 'Edits',
  },
  ar: {
    shop: 'المتجر',
    cart: 'السلة',
    account: 'حسابك',
    brand: 'مارفل',
    menu: 'الأقسام',
    all: 'عرض الكل',
    announce: 'الدفع عند الاستلام · توصيل لكل محافظات مصر',
    edits: 'تشكيلات',
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
 *
 * There is deliberately no search, account or wishlist control here. None of
 * those exist yet, and an icon that opens nothing is worse than an absent one —
 * it reads as a broken shop rather than an unfinished one.
 */
export default function Header() {
  const { locale, href, switchTo } = useLocale();
  const { itemCount } = useCart();
  const pageContext = usePageContext();
  const copy = COPY[locale] ?? COPY.en;

  // Supplied by each page's +data. Absent on a page that did not load it, in
  // which case the shop still works — it just navigates from the footer.
  const categories = pageContext?.data?.categories ?? [];
  const collections = pageContext?.data?.collections ?? [];

  return (
    <header className={styles.header}>
      <p className={styles.announce}>{copy.announce}</p>

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

            {collections.length ? (
              <li className={styles.topItem}>
                <a
                  className={styles.topLink}
                  href={href(`/edit/${collections[0].slug}`)}
                >
                  {copy.edits}
                </a>
                <div className={styles.panel}>
                  <ul className={styles.children}>
                    {collections.map((collection) => (
                      <li key={collection.id}>
                        <a href={href(`/edit/${collection.slug}`)}>
                          {collection.title}
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              </li>
            ) : null}
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

          {/* Before the cart, so the tab order is identity then basket -- and
              deliberately not a sign-in/sign-out toggle. Whether anyone is
              signed in is only known after hydration, so a header that renders
              one or the other would flicker on every page load. The link says
              the same thing either way and the page behind it decides. */}
          <a className={styles.account} href={href('/account')}>
            <span aria-hidden="true" className={styles.cartGlyph}>
              <svg viewBox="0 0 24 24" width="20" height="20" fill="none">
                <path
                  d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z"
                  stroke="currentColor"
                  strokeWidth="1.6"
                />
                <path
                  d="M4.5 20a7.5 7.5 0 0 1 15 0"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                />
              </svg>
            </span>
            <span className="visually-hidden">{copy.account}</span>
          </a>

          <a className={styles.cart} href={href('/cart')}>
            <span aria-hidden="true" className={styles.cartGlyph}>
              {/* Inline, not an icon font: one shape does not justify a webfont
                  request, and an SVG scales with the text around it. */}
              <svg viewBox="0 0 24 24" width="20" height="20" fill="none">
                <path
                  d="M4 7h16l-1.2 11.2a2 2 0 0 1-2 1.8H7.2a2 2 0 0 1-2-1.8L4 7Z"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinejoin="round"
                />
                <path
                  d="M9 7V5.5a3 3 0 0 1 6 0V7"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                />
              </svg>
            </span>
            <span className="visually-hidden">{copy.cart}</span>
            <span className={styles.count}>{itemCount}</span>
          </a>
        </div>
      </div>
    </header>
  );
}
