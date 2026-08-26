import ProductCard from '../../components/common/ProductCard/ProductCard.jsx';
import { useData } from '../../hooks/useData.js';
import { useLocale } from '../../hooks/useLocale.jsx';
import { useTrackOnce } from '../../hooks/useTrackEvent.js';
import { search as searchEvent, viewItemList } from '../../utils/events.js';
import styles from './search.module.scss';

/**
 * Search results.
 *
 * Two events, not one. `search` reports the term and how many results it found
 * -- a term with zero results is the most actionable row in the whole report,
 * because it is somebody naming a thing the shop does not sell. `view_item_list`
 * reports the impressions, under the `search` list identity so that a sale
 * traceable back to a search can be told apart from one that came off a
 * category page.
 *
 * Both are keyed on the query, so paging or re-searching fires them again while
 * a re-render does not.
 */
export default function SearchPage() {
  const { q, listing, copy } = useData();
  const { locale } = useLocale();

  useTrackOnce(`${locale}:search:${q}:${listing.page ?? 1}`, () =>
    q ? searchEvent(listing.query ?? q, { locale, resultCount: listing.total ?? 0 }) : null,
  );

  useTrackOnce(`${locale}:search-impressions:${q}:${listing.page ?? 1}`, () =>
    q && listing.items?.length
      ? viewItemList(listing.items, {
          listId: listing.item_list_id ?? 'search',
          listName: listing.item_list_name ?? 'Search results',
          locale,
        })
      : null,
  );

  return (
    <div className={styles.page}>
      <header className={styles.intro}>
        <h1>{copy.heading}</h1>

        {/* A GET form, so the results have a URL. A JS-only box would make
            every search the same address -- unlinkable, unshareable, and gone
            on reload. */}
        <form className={styles.box} method="get" role="search">
          <label className="visually-hidden" htmlFor="q">
            {copy.placeholder}
          </label>
          <input
            id="q"
            type="search"
            name="q"
            defaultValue={q}
            placeholder={copy.placeholder}
            autoComplete="off"
          />
          <button type="submit">{copy.submit}</button>
        </form>

        {q ? (
          <p className={styles.count}>
            {copy.resultsFor} <strong>{q}</strong> · {listing.total} {copy.results}
          </p>
        ) : (
          <p className={styles.count}>{copy.prompt}</p>
        )}
      </header>

      {q && listing.items?.length === 0 ? (
        <div className={styles.empty}>
          <p>{copy.empty}</p>
          <p className={styles.hint}>{copy.emptyHint}</p>
        </div>
      ) : null}

      {listing.items?.length ? (
        <div className={styles.grid}>
          {listing.items.map((product, index) => (
            // The list identity travels on each item from the API, which is
            // what keeps a select_item consistent with the impression above it.
            <ProductCard
              key={product.id}
              product={product}
              index={index}
              listId={listing.item_list_id ?? 'search'}
              listName={listing.item_list_name ?? 'Search results'}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}
