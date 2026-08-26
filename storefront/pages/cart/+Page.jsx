import Price from '../../components/common/Price/Price.jsx';
import { useCart } from '../../hooks/useCart.jsx';
import { useLocale } from '../../hooks/useLocale.jsx';
import { useTrackOnce } from '../../hooks/useTrackEvent.js';
import { pushEvent } from '../../services/dataLayer.js';
import { removeFromCart, viewCart } from '../../utils/events.js';
import { money } from '../../utils/format.js';
import styles from './cart.module.scss';

const COPY = {
  en: {
    heading: 'Your cart',
    empty: 'Your cart is empty.',
    keepShopping: 'Continue shopping',
    quantity: 'Quantity',
    remove: 'Remove',
    subtotal: 'Subtotal',
    discount: 'Discount',
    total: 'Total',
    checkout: 'Checkout',
    priceChanged: 'The price of this item changed while it was in your cart.',
  },
  ar: {
    heading: 'سلتك',
    empty: 'سلتك فارغة.',
    keepShopping: 'متابعة التسوق',
    quantity: 'الكمية',
    remove: 'إزالة',
    subtotal: 'المجموع الفرعي',
    discount: 'الخصم',
    total: 'الإجمالي',
    checkout: 'إتمام الطلب',
    priceChanged: 'تغيّر سعر هذا المنتج أثناء وجوده في سلتك.',
  },
};

/**
 * The basket.
 *
 * Rendered entirely after hydration. It is per-shopper state with nothing to
 * index — and server-rendering it would put a basket somewhere a cache could
 * hand it to the next visitor.
 */
export default function CartPage() {
  const { cart, busy, error, setQuantity, remove } = useCart();
  const { locale, href } = useLocale();
  const copy = COPY[locale] ?? COPY.en;

  const items = cart?.items ?? [];

  // Keyed on the cart token, same rule as begin_checkout: returning to the
  // cart with the same basket does not count as viewing it again.
  useTrackOnce(items.length > 0 ? cart?.token : null, () => viewCart(cart, { locale }));

  return (
    <>
      <h1>{copy.heading}</h1>

      {error ? (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      ) : null}

      {items.length === 0 ? (
        <p>
          {copy.empty} <a href={href('/')}>{copy.keepShopping}</a>
        </p>
      ) : (
        <div className={styles.layout}>
          <ul className={styles.lines}>
            {items.map((item) => (
              <li key={item.variant_id} className={styles.line}>
                <div className={styles.lineMain}>
                  <span className={styles.title}>{item.title}</span>
                  {/* Same rule as the order number: a SKU is Latin in both
                      languages and must not be reordered by its neighbours. */}
                  <span className={styles.sku}>
                    <bdi>{item.sku}</bdi>
                  </span>
                  {/* The cart holds a price snapshot; the catalogue may have
                      moved since. Saying so beats silently repricing. */}
                  {item.price_changed ? (
                    <span className={styles.notice}>{copy.priceChanged}</span>
                  ) : null}
                </div>

                <label className={styles.quantity}>
                  <span className="visually-hidden">{copy.quantity}</span>
                  <input
                    type="number"
                    min="1"
                    value={item.quantity}
                    disabled={busy}
                    onChange={(event) => {
                      const raw = event.target.value;
                      // Number('') is 0. Selecting the field and pressing
                      // Backspace before typing a new quantity produces this
                      // exact intermediate value -- it is not the shopper
                      // choosing zero, and must not read as a removal.
                      if (raw === '') return;
                      const quantity = Number(raw);
                      if (Number.isNaN(quantity)) return;
                      // The API treats quantity: 0 as a removal, not a
                      // set-to-zero -- so this is the same event the Remove
                      // button fires, reached by a second path.
                      if (quantity === 0) pushEvent(removeFromCart(item, { locale }));
                      setQuantity(item.variant_id, quantity);
                    }}
                  />
                </label>

                <span className={styles.lineTotal}>{money(item.line_total, locale)}</span>

                <button
                  type="button"
                  className={styles.remove}
                  disabled={busy}
                  onClick={() => {
                    // Fired before the async removal, same rule as
                    // add_to_cart on the product page: the event exists even
                    // if the request that follows it fails.
                    pushEvent(removeFromCart(item, { locale }));
                    remove(item.variant_id);
                  }}
                >
                  {copy.remove}
                </button>
              </li>
            ))}
          </ul>

          <aside className={styles.summary}>
            <dl>
              <dt>{copy.subtotal}</dt>
              <dd>{money(cart.subtotal, locale)}</dd>
              {Number(cart.discount_total) > 0 ? (
                <>
                  <dt>{copy.discount}</dt>
                  <dd className={styles.discount}>−{money(cart.discount_total, locale)}</dd>
                </>
              ) : null}
              <dt className={styles.totalLabel}>{copy.total}</dt>
              <dd className={styles.totalValue}>{money(cart.total, locale)}</dd>
            </dl>

            <a className={styles.checkout} href={href('/checkout')}>
              {copy.checkout}
            </a>
          </aside>
        </div>
      )}
    </>
  );
}
