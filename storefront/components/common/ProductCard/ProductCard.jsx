import Price from '../Price/Price.jsx';
import ProductImage from '../ProductImage/ProductImage.jsx';
import { useLocale } from '../../../hooks/useLocale.jsx';
import styles from './ProductCard.module.scss';

const COPY = {
  en: { sale: 'Sale', colours: 'Colours', sizes: 'Sizes', soldOut: 'Sold out' },
  ar: { sale: 'تخفيض', colours: 'الألوان', sizes: 'المقاسات', soldOut: 'نفدت الكمية' },
};

/**
 * One product in a listing.
 *
 * The image carries explicit width and height because they are what hold CLS
 * under 0.1 — section 8A treats a missing dimension as a layout-shift bug, and
 * the database refuses a row without them precisely so this can rely on them.
 *
 * ``loading`` is eager for the first few cards and lazy after: lazy-loading
 * something already in the viewport delays the largest contentful paint rather
 * than helping it.
 *
 * The hover image is rendered underneath rather than swapped in on hover. A
 * swap would fetch the second file at the moment the pointer arrives, so the
 * first hover shows a blank frame; stacking them means the browser has it
 * already. It is `aria-hidden` — it is the same product, and announcing it
 * twice tells a screen-reader user there are two.
 */
export default function ProductCard({ product, index = 0 }) {
  const { href, locale } = useLocale();
  const copy = COPY[locale] ?? COPY.en;

  const image = product.primary_image;
  const hover = product.hover_image;
  const onSale = product.sale_price != null;
  const colours = product.colors ?? [];
  const sizes = product.sizes ?? [];

  return (
    <article className={styles.card}>
      <a className={styles.link} href={href(`/products/${product.slug}`)}>
        <div className={styles.frame}>
          <ProductImage
            image={image}
            eager={index < 4}
            priority={index === 0}
            className={styles.image}
          />
          {hover ? (
            <ProductImage
              image={hover}
              eager={index < 4}
              className={styles.hoverImage}
              aria-hidden="true"
            />
          ) : null}
          {onSale ? <span className={styles.badge}>{copy.sale}</span> : null}
        </div>

        <h2 className={styles.title}>{product.title}</h2>
      </a>

      <Price price={product.price} salePrice={product.sale_price} />

      {colours.length ? (
        <ul className={styles.swatches} aria-label={copy.colours}>
          {colours.slice(0, 5).map((colour) => (
            <li key={colour.code}>
              {/* The dot is decoration; the label is the accessible name, and
                  it is the localized one. */}
              <span
                className={styles.swatch}
                data-colour={colour.code}
                title={colour.label}
              />
              <span className="visually-hidden">{colour.label}</span>
            </li>
          ))}
          {colours.length > 5 ? (
            <li className={styles.more}>+{colours.length - 5}</li>
          ) : null}
        </ul>
      ) : null}

      {/* In-stock sizes only — the API filters them, because a size shown on a
          card is an implicit promise it can be bought. */}
      {sizes.length ? (
        <ul className={styles.sizes} aria-label={copy.sizes}>
          {sizes.map((size) => (
            <li key={size.code}>{size.label}</li>
          ))}
        </ul>
      ) : (
        <p className={styles.soldOut}>{copy.soldOut}</p>
      )}
    </article>
  );
}
