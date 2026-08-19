import Price from '../Price/Price.jsx';
import ProductImage from '../ProductImage/ProductImage.jsx';
import { useLocale } from '../../../hooks/useLocale.jsx';
import styles from './ProductCard.module.scss';

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
 */
export default function ProductCard({ product, index = 0 }) {
  const { href } = useLocale();
  const image = product.primary_image;

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
        </div>
        <h2 className={styles.title}>{product.title}</h2>
      </a>
      <p className={styles.brand}>{product.brand}</p>
      <Price price={product.price} salePrice={product.sale_price} />
    </article>
  );
}
