import { useData } from '../../hooks/useData.js';
import { useLocale } from '../../hooks/useLocale.jsx';
import { useTrackOnce } from '../../hooks/useTrackEvent.js';
import { viewItemList } from '../../utils/events.js';
import ProductCard from '../../components/common/ProductCard/ProductCard.jsx';
import styles from './index.module.scss';

export default function HomePage() {
  const { listing, copy } = useData();
  const { locale } = useLocale();

  // Section 5's item_list_id. The same value travels with an add to cart and
  // ends up snapshotted on order_items, which is what makes the journey from
  // listing to revenue reconstructable.
  const listId = 'new_in';
  const listName = 'New in';
  useTrackOnce(`${locale}:${listId}`, () =>
    viewItemList(listing.items, { listId, listName, locale }),
  );

  return (
    <>
      <h1>{copy.heading}</h1>

      {listing.items.length === 0 ? (
        <p>{/* An empty catalogue is a state, not an error. */}</p>
      ) : (
        <div className={styles.grid}>
          {listing.items.map((product, index) => (
            <ProductCard key={product.id} product={product} index={index} />
          ))}
        </div>
      )}
    </>
  );
}
