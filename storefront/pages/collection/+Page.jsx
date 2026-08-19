import FilterPanel, {
  buildHref,
} from '../../components/common/FilterPanel/FilterPanel.jsx';
import ProductCard from '../../components/common/ProductCard/ProductCard.jsx';
import { useData } from '../../hooks/useData.js';
import { useLocale } from '../../hooks/useLocale.jsx';
import { useTrackOnce } from '../../hooks/useTrackEvent.js';
import { viewItemList } from '../../utils/events.js';
import styles from '../category/category.module.scss';

const SORTS = ['featured', 'newest', 'price_asc', 'price_desc'];

export default function CollectionPage() {
  const { collection, listing, filters, copy } = useData();
  const { locale, href } = useLocale();

  const basePath = `/edit/${collection.slug}`;
  useTrackOnce(`${locale}:${collection.list_id}:${JSON.stringify(filters)}`, () =>
    viewItemList(listing.items, {
      listId: collection.list_id,
      listName: collection.title,
      locale,
    }),
  );

  const facets = listing.facets ?? { sizes: [], colors: [] };

  return (
    <div className={styles.layout}>
      <header className={styles.intro}>
        <nav className={styles.breadcrumb} aria-label="Breadcrumb">
          <a href={href('/')}>{locale === 'ar' ? 'الرئيسية' : 'Home'}</a>
          <span aria-hidden="true">/</span>
          <span aria-current="page">{collection.title}</span>
        </nav>
        <h1>{collection.title}</h1>
        {collection.description ? (
          <p className={styles.blurb}>{collection.description}</p>
        ) : null}
      </header>

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
