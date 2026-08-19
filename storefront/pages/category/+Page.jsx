import FilterPanel, {
  buildHref,
} from '../../components/common/FilterPanel/FilterPanel.jsx';
import ProductCard from '../../components/common/ProductCard/ProductCard.jsx';
import { useData } from '../../hooks/useData.js';
import { useLocale } from '../../hooks/useLocale.jsx';
import { useTrackOnce } from '../../hooks/useTrackEvent.js';
import { viewItemList } from '../../utils/events.js';
import styles from './category.module.scss';

const SORTS = ['featured', 'newest', 'price_asc', 'price_desc'];

export default function CategoryPage() {
  const { category, listing, filters, copy } = useData();
  const { locale, href } = useLocale();

  const basePath = `/c/${category.slug}`;
  // The list identity is the category's own list_id, not a per-page invention.
  // The same string travels with an add to cart and is snapshotted onto
  // order_items, which is what makes listing-to-revenue reconstructable.
  useTrackOnce(`${locale}:${category.list_id}:${JSON.stringify(filters)}`, () =>
    viewItemList(listing.items, {
      listId: category.list_id,
      listName: category.title,
      locale,
    }),
  );

  const facets = listing.facets ?? { sizes: [], colors: [] };

  return (
    <div className={styles.layout}>
      <header className={styles.intro}>
        <nav className={styles.breadcrumb} aria-label="Breadcrumb">
          <a href={href('/')}>{locale === 'ar' ? 'الرئيسية' : 'Home'}</a>
          {category.parent ? (
            <>
              <span aria-hidden="true">/</span>
              <a href={href(`/c/${category.parent.slug}`)}>{category.parent.title}</a>
            </>
          ) : null}
          <span aria-hidden="true">/</span>
          <span aria-current="page">{category.title}</span>
        </nav>

        <h1>{category.title}</h1>
        {category.description ? (
          <p className={styles.blurb}>{category.description}</p>
        ) : null}
      </header>

      {/* Child categories as their own entry points. On a phone the hover menu
          is hidden, so this is the only way down the tree — and it is real
          markup either way. */}
      {category.children?.length ? (
        <ul className={styles.children}>
          {category.children.map((child) => (
            <li key={child.id}>
              <a href={href(`/c/${child.slug}`)}>{child.title}</a>
            </li>
          ))}
        </ul>
      ) : null}

      <div className={styles.body}>
        <FilterPanel
          basePath={basePath}
          filters={filters}
          facets={facets}
          copy={copy}
          total={listing.total}
        />

        <section className={styles.results}>
          <div className={styles.toolbar}>
            <span className={styles.total}>
              {listing.total} {copy.results}
            </span>
            <ul className={styles.sorts} aria-label={copy.sort}>
              {SORTS.map((sort) => (
                <li key={sort}>
                  <a
                    className={filters.sort === sort ? styles.sortOn : styles.sort}
                    href={buildHref(href(basePath), filters, { sort })}
                    aria-current={filters.sort === sort ? 'true' : undefined}
                  >
                    {copy.sorts[sort]}
                  </a>
                </li>
              ))}
            </ul>
          </div>

          {listing.items.length === 0 ? (
            <p className={styles.empty}>{copy.empty}</p>
          ) : (
            <div className={styles.grid}>
              {listing.items.map((product, index) => (
                <ProductCard key={product.id} product={product} index={index} />
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
