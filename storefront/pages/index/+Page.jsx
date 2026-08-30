import ProductCard from '../../components/common/ProductCard/ProductCard.jsx';
import { useData } from '../../hooks/useData.js';
import { useLocale } from '../../hooks/useLocale.jsx';
import { useTrackOnce } from '../../hooks/useTrackEvent.js';
import { viewItemList } from '../../utils/events.js';
import styles from './index.module.scss';

/** A centred heading with a rule running out to each side. */
function Divider({ children, href, more }) {
  return (
    <div className={styles.divider}>
      <span className={styles.rule} aria-hidden="true" />
      <h2 className={styles.dividerHeading}>{children}</h2>
      <span className={styles.rule} aria-hidden="true" />
      {href ? (
        <a className={styles.dividerLink} href={href}>
          {more}
        </a>
      ) : null}
    </div>
  );
}

function Showcase({ listing, emptyNote, listId, listName }) {
  if (!listing?.items?.length) return <p className={styles.empty}>{emptyNote}</p>;
  return (
    <div className={styles.grid}>
      {listing.items.map((product, index) => (
        <ProductCard
          key={product.id}
          product={product}
          index={index}
          listId={listId}
          listName={listName}
        />
      ))}
    </div>
  );
}

export default function HomePage() {
  const { listing, shoes, bags, shoesSlug, bagsSlug, categories, collections, copy } = useData();
  const { locale, href } = useLocale();
  const shoesPath = `/c/${shoesSlug}`;
  const bagsPath = `/c/${bagsSlug}`;

  // Section 5's item_list_id. The same value travels with an add to cart and
  // ends up snapshotted on order_items, which is what makes the journey from
  // listing to revenue reconstructable.
  const listId = 'new_in';
  useTrackOnce(`${locale}:${listId}`, () =>
    viewItemList(listing.items, { listId, listName: copy.newIn, locale }),
  );

  // The hero borrows the lead category's artwork until an operator sets one.
  const heroImage = categories[0]?.image?.url ?? null;
  const tiles = categories.flatMap((parent) => parent.children ?? []);

  return (
    <>
      <section
        className={styles.hero}
        // Inline because the URL is data, not styling: it changes with the
        // catalogue and cannot live in a stylesheet.
        style={heroImage ? { backgroundImage: `url(${heroImage})` } : undefined}
      >
        <div className={styles.heroScrim} aria-hidden="true" />
        <div className={styles.heroText}>
          <span className={styles.eyebrow}>{copy.eyebrow}</span>
          <h1>{copy.heroTitle}</h1>
          <p>{copy.heroBody}</p>
          <div className={styles.heroActions}>
            <a className={styles.heroCta} href={href(shoesPath)}>
              {copy.heroCta}
            </a>
            <a className={styles.heroGhost} href={href(bagsPath)}>
              {copy.heroCtaAlt}
            </a>
          </div>
        </div>
      </section>

      {tiles.length ? (
        <section className={styles.section}>
          <Divider>{copy.shopCategory}</Divider>
          <ul className={styles.tiles}>
            {tiles.map((child) => (
              <li key={child.id}>
                <a href={href(`/c/${child.slug}`)}>
                  <span className={styles.tileFrame}>
                    {child.image ? (
                      <img
                        src={child.image.url}
                        alt=""
                        loading="lazy"
                        decoding="async"
                      />
                    ) : null}
                  </span>
                  <span className={styles.tileLabel}>{child.title}</span>
                </a>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className={styles.section}>
        <Divider href={href(shoesPath)} more={copy.viewAll}>
          {copy.shoes}
        </Divider>
        <Showcase listing={shoes} listId="shoes" listName={copy.shoes} />
      </section>

      <section className={styles.section}>
        <Divider href={href(bagsPath)} more={copy.viewAll}>
          {copy.bags}
        </Divider>
        <Showcase listing={bags} listId="bags" listName={copy.bags} />
      </section>

      <section className={styles.section}>
        <Divider href={href(shoesPath)} more={copy.viewAll}>
          {copy.newIn}
        </Divider>
        <Showcase listing={listing} listId={listId} listName={copy.newIn} />
      </section>

      {collections.length ? (
        <section className={styles.section}>
          <Divider>{copy.edits}</Divider>
          <ul className={styles.edits}>
            {collections.map((collection) => (
              <li key={collection.id}>
                <a href={href(`/edit/${collection.slug}`)}>
                  <span className={styles.editFrame}>
                    {collection.image ? (
                      <img
                        src={collection.image.url}
                        alt=""
                        loading="lazy"
                        decoding="async"
                      />
                    ) : null}
                  </span>
                  <span className={styles.editBody}>
                    <span className={styles.editTitle}>{collection.title}</span>
                    <span className={styles.editCta}>{copy.viewAll}</span>
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <ul className={styles.promises}>
        {copy.promises.map(([title, body]) => (
          <li key={title}>
            <span className={styles.promiseTitle}>{title}</span>
            <span className={styles.promiseBody}>{body}</span>
          </li>
        ))}
      </ul>
    </>
  );
}
