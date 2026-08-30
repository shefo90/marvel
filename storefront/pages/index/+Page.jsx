import { useEffect, useState } from 'react';

import ProductCard from '../../components/common/ProductCard/ProductCard.jsx';
import { useData } from '../../hooks/useData.js';
import { useLocale } from '../../hooks/useLocale.jsx';
import { useTrackOnce } from '../../hooks/useTrackEvent.js';
import { viewItemList } from '../../utils/events.js';
import styles from './index.module.scss';

const ROTATE_MS = 5000;

/**
 * Cross-fades through a set of background images, sized and styled by
 * whatever `layerClass`/`activeClass` the caller passes -- the hero and each
 * Edits tile share this same rotator over different-sized boxes.
 *
 * Callers are responsible for only ever passing already locale-scoped,
 * published-only, non-archived images (the same `listProducts` result every
 * other section on this page renders from), never a separate, easier-to-drift
 * query.
 */
function RotatingLayers({ slides, layerClass, activeClass }) {
  const [active, setActive] = useState(0);

  useEffect(() => {
    if (slides.length < 2) return undefined;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return undefined;
    const id = setInterval(() => {
      setActive((current) => (current + 1) % slides.length);
    }, ROTATE_MS);
    return () => clearInterval(id);
    // Re-run only if the number of slides changes, not on every `active` tick.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slides.length]);

  return slides.map((image, index) => (
    <div
      key={image.url}
      className={index === active ? `${layerClass} ${activeClass}` : layerClass}
      style={{ backgroundImage: `url(${image.url})` }}
      aria-hidden="true"
    />
  ));
}

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

  // The hero rotates through the newest published products' own photos. A
  // brand-new shop with nothing published yet falls back to the lead
  // category's artwork so the hero is never just an empty scrim.
  const heroSlides = listing.items.map((product) => product.primary_image).filter(Boolean);
  const heroFallback = categories[0]?.image ?? null;
  const slides = heroSlides.length ? heroSlides : heroFallback ? [heroFallback] : [];
  const tiles = categories.flatMap((parent) => parent.children ?? []);

  return (
    <>
      <section className={styles.hero}>
        <RotatingLayers
          slides={slides}
          layerClass={styles.heroLayer}
          activeClass={styles.heroLayerActive}
        />
        <div className={styles.heroScrim} aria-hidden="true" />
        <div className={styles.heroText}>
          <span className={styles.eyebrow}>{copy.eyebrow}</span>
          <h1>{copy.heroTitle}</h1>
          <p>{copy.heroBody}</p>
          <div className={styles.heroActions}>
            <a className={styles.heroCta} href={href('/new-in')}>
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
        <Divider href={href('/new-in')} more={copy.viewAll}>
          {copy.newIn}
        </Divider>
        <Showcase listing={listing} listId={listId} listName={copy.newIn} />
      </section>

      {collections.length ? (
        <section className={styles.section}>
          <Divider>{copy.edits}</Divider>
          <ul className={styles.edits}>
            {collections.map((collection) => {
              const editSlides = collection.tileImages?.length
                ? collection.tileImages
                : collection.image
                  ? [collection.image]
                  : [];
              return (
                <li key={collection.id}>
                  <a href={href(`/edit/${collection.slug}`)}>
                    <span className={styles.editFrame}>
                      <RotatingLayers
                        slides={editSlides}
                        layerClass={styles.editLayer}
                        activeClass={styles.editLayerActive}
                      />
                    </span>
                    <span className={styles.editBody}>
                      <span className={styles.editTitle}>{collection.title}</span>
                      <span className={styles.editCta}>{copy.viewAll}</span>
                    </span>
                  </a>
                </li>
              );
            })}
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
