import FilterPanel, {
  buildHref,
} from '../../components/common/FilterPanel/FilterPanel.jsx';
import ProductCard from '../../components/common/ProductCard/ProductCard.jsx';
import { useData } from '../../hooks/useData.js';
import { useLocale } from '../../hooks/useLocale.jsx';
import { useTrackOnce } from '../../hooks/useTrackEvent.js';
import { viewItemList } from '../../utils/events.js';
// Shared with the category page rather than duplicated: this is the same
// "filters beside a product grid" layout, just without a category to be under.
import styles from '../category/category.module.scss';

const SORTS = ['newest', 'featured', 'price_asc', 'price_desc'];

export default function NewInPage() {
  const { listing, filters, copy } = useData();
  const { locale, href } = useLocale();

  const basePath = '/new-in';
  // A fixed list identity, the same one the homepage's "New in" rail already
  // uses -- so a product added to cart from either place snapshots the same
  // item_list_id onto the order line.
  const listId = 'new_in';
  useTrackOnce(`${locale}:${listId}:${JSON.stringify(filters)}`, () =>
    viewItemList(listing.items, { listId, listName: copy.heading, locale }),
  );

  const facets = listing.facets ?? { sizes: [], colors: [] };

  return (
    <div className={styles.layout}>
      <header className={styles.intro}>
        <h1>{copy.heading}</h1>
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
                <ProductCard
                  key={product.id}
                  product={product}
                  index={index}
                  listId={listId}
                  listName={copy.heading}
                />
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
