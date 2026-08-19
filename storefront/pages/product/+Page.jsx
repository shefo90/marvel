import { useState } from 'react';

import Price from '../../components/common/Price/Price.jsx';
import ProductImage from '../../components/common/ProductImage/ProductImage.jsx';
import { useCart } from '../../hooks/useCart.jsx';
import { useData } from '../../hooks/useData.js';
import { useLocale } from '../../hooks/useLocale.jsx';
import styles from './product.module.scss';

const COPY = {
  en: {
    size: 'Size',
    add: 'Add to cart',
    adding: 'Adding…',
    added: 'Added to your cart',
    soldOut: 'Sold out',
    details: 'Details',
  },
  ar: {
    size: 'المقاس',
    add: 'أضف إلى السلة',
    adding: 'جارٍ الإضافة…',
    added: 'تمت الإضافة إلى سلتك',
    soldOut: 'نفدت الكمية',
    details: 'التفاصيل',
  },
};

/**
 * The product page.
 *
 * The variant picker writes to component state only. Changing size must not
 * change the URL: one product is one page in one language, and a URL per size
 * would fragment the very cluster the canonical tag establishes.
 */
export default function ProductPage() {
  const { product } = useData();
  const { locale } = useLocale();
  const { add, busy } = useCart();
  const copy = COPY[locale] ?? COPY.en;

  const sellable = (product.variants ?? []).filter((v) => v.stock_quantity > 0);
  const initial =
    sellable.find((v) => v.sku === product.default_variant_sku) ?? sellable[0] ?? null;
  const [selected, setSelected] = useState(initial);
  const [done, setDone] = useState(false);

  const image = product.images?.find((i) => i.is_primary) ?? product.images?.[0];

  const onAdd = async () => {
    if (!selected) return;
    setDone(false);
    await add({
      sku: selected.sku,
      quantity: 1,
      // Section 5 list attribution, sent at add time because it cannot be
      // reconstructed afterwards.
      listId: 'pdp',
      listName: 'Product detail',
      index: 0,
    });
    setDone(true);
  };

  return (
    <div className={styles.layout}>
      <div className={styles.gallery}>
        <ProductImage image={image} eager priority className={styles.hero} />
        {(product.images ?? []).slice(1).map((extra) => (
          <ProductImage key={extra.id} image={extra} className={styles.thumb} />
        ))}
      </div>

      <div className={styles.detail}>
        <h1>{product.title}</h1>
        <p className={styles.brand}>{product.brand}</p>

        <div className={styles.price}>
          <Price price={selected?.price} salePrice={selected?.sale_price} />
        </div>

        {sellable.length === 0 ? (
          <p className={styles.soldOut}>{copy.soldOut}</p>
        ) : (
          <>
            <fieldset className={styles.sizes}>
              <legend>{copy.size}</legend>
              {sellable.map((variant) => (
                <label key={variant.sku} className={styles.sizeOption}>
                  <input
                    type="radio"
                    name="variant"
                    value={variant.sku}
                    checked={selected?.sku === variant.sku}
                    onChange={() => {
                      setSelected(variant);
                      setDone(false);
                    }}
                  />
                  <span>{variant.size ?? variant.variant_title}</span>
                </label>
              ))}
            </fieldset>

            <button
              type="button"
              className={styles.add}
              onClick={onAdd}
              disabled={busy || !selected}
            >
              {busy ? copy.adding : copy.add}
            </button>

            {/* Announced, not merely shown: a shopper using a screen reader
                otherwise has no way to know the click did anything. */}
            <p role="status" aria-live="polite" className={styles.status}>
              {done ? copy.added : ''}
            </p>
          </>
        )}

        {product.description ? (
          <section className={styles.description}>
            <h2>{copy.details}</h2>
            <p>{product.description}</p>
          </section>
        ) : null}
      </div>
    </div>
  );
}
