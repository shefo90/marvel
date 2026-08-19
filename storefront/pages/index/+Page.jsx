import ProductCard from '../../components/common/ProductCard/ProductCard.jsx';
import { useData } from '../../hooks/useData.js';
import { useLocale } from '../../hooks/useLocale.jsx';
import { useTrackOnce } from '../../hooks/useTrackEvent.js';
import { viewItemList } from '../../utils/events.js';
import styles from './index.module.scss';

export default function HomePage() {
  const { listing, categories, collections, copy } = useData();
  const { locale, href } = useLocale();

  // Section 5's item_list_id. The same value travels with an add to cart and
  // ends up snapshotted on order_items, which is what makes the journey from
  // listing to revenue reconstructable.
  const listId = 'new_in';
  const listName = copy.newIn;
  useTrackOnce(`${locale}:${listId}`, () =>
    viewItemList(listing.items, { listId, listName, locale }),
  );

  return (
    <>
      <section className={styles.hero}>
        <div className={styles.heroText}>
          <span className={styles.eyebrow}>{copy.eyebrow}</span>
          <h1>{copy.heroTitle}</h1>
          <p>{copy.heroBody}</p>
          <a className={styles.heroCta} href={href('/c/shoes')}>
            {copy.heroCta}
          </a>
        </div>
      </section>

      {categories.length ? (
        <section className={styles.section}>
          <div className={styles.sectionHead}>
            <h2 className={styles.sectionHeading}>{copy.shopCategory}</h2>
          </div>
          {categories.map((parent) => (
            <div key={parent.id} className={styles.group}>
              <div className={styles.groupHead}>
                <h3>{parent.title}</h3>
                <a href={href(`/c/${parent.slug}`)}>{copy.viewAll}</a>
              </div>
              <ul className={styles.tiles}>
                {parent.children.map((child) => (
                  <li key={child.id}>
                    <a href={href(`/c/${child.slug}`)}>{child.title}</a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </section>
      ) : null}

      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <h2 className={styles.sectionHeading}>{copy.newIn}</h2>
          <a className={styles.sectionLink} href={href('/c/shoes')}>
            {copy.viewAll}
          </a>
        </div>

        {listing.items.length === 0 ? (
          /* An empty catalogue is a state, not an error. */
          <p className={styles.empty} />
        ) : (
          <div className={styles.grid}>
            {listing.items.map((product, index) => (
              <ProductCard key={product.id} product={product} index={index} />
            ))}
          </div>
        )}
      </section>

      {collections.length ? (
        <section className={styles.section}>
          <div className={styles.sectionHead}>
            <h2 className={styles.sectionHeading}>{copy.edits}</h2>
          </div>
          <ul className={styles.edits}>
            {collections.map((collection) => (
              <li key={collection.id}>
                <a href={href(`/edit/${collection.slug}`)}>
                  <span className={styles.editTitle}>{collection.title}</span>
                  {collection.description ? (
                    <span className={styles.editBlurb}>{collection.description}</span>
                  ) : null}
                </a>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
}
