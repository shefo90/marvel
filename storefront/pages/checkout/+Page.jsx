import { useState } from 'react';
import { navigate } from 'vike/client/router';

import { useCart } from '../../hooks/useCart.jsx';
import { useLocale } from '../../hooks/useLocale.jsx';
import { useTrackOnce } from '../../hooks/useTrackEvent.js';
import { pushEvent } from '../../services/dataLayer.js';
import { beginCheckout, purchase } from '../../utils/events.js';
import { clearCartToken } from '../../services/api.js';
import { placeOrder } from '../../services/cart.service.js';
import { money } from '../../utils/format.js';
import styles from './checkout.module.scss';

const COPY = {
  en: {
    heading: 'Checkout',
    contact: 'Contact',
    email: 'Email',
    phone: 'Phone',
    firstName: 'First name',
    lastName: 'Last name',
    delivery: 'Delivery address',
    recipient: 'Recipient name',
    governorate: 'Governorate',
    city: 'City',
    street: 'Street address',
    building: 'Building',
    payment: 'Payment',
    cod: 'Cash on delivery',
    codNote: 'Pay the courier when your order arrives.',
    total: 'Total',
    place: 'Place order',
    placing: 'Placing your order…',
    empty: 'Your cart is empty.',
    required: 'Please fill in every required field.',
    keepShopping: 'Continue shopping',
  },
  ar: {
    heading: 'إتمام الطلب',
    contact: 'بيانات التواصل',
    email: 'البريد الإلكتروني',
    phone: 'رقم الهاتف',
    firstName: 'الاسم الأول',
    lastName: 'اسم العائلة',
    delivery: 'عنوان التوصيل',
    recipient: 'اسم المستلم',
    governorate: 'المحافظة',
    city: 'المدينة',
    street: 'العنوان',
    building: 'رقم المبنى',
    payment: 'الدفع',
    cod: 'الدفع عند الاستلام',
    codNote: 'ادفع لمندوب التوصيل عند وصول طلبك.',
    total: 'الإجمالي',
    place: 'تأكيد الطلب',
    placing: 'جارٍ تأكيد طلبك…',
    empty: 'سلتك فارغة.',
    required: 'يرجى ملء جميع الحقول المطلوبة.',
    keepShopping: 'متابعة التسوق',
  },
};

/**
 * Turns the API's error shape into something a shopper can act on.
 *
 * A plain string (e.g. "cart is empty", "only 2 left for this size") is
 * already meant to be read as-is. A validation failure instead arrives as a
 * list of `{loc, msg}` entries -- one per field -- which is why the previous
 * version of this handler collapsed every non-string case to one generic
 * "fill in every field" message: that's true for a missing field, but the
 * exact same code path fired for a stray extra space, a length limit, or
 * anything else the shape check catches, none of which "fill in every field"
 * actually describes.
 */
function describeError(detail, copy) {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length) {
    const labels = {
      email: copy.email,
      phone: copy.phone,
      first_name: copy.firstName,
      last_name: copy.lastName,
      recipient_name: copy.recipient,
      governorate: copy.governorate,
      city: copy.city,
      street_address: copy.street,
      building: copy.building,
    };
    const message = detail
      .map((entry) => {
        const field = entry?.loc?.[entry.loc.length - 1];
        const label = labels[field];
        return label ? `${label}: ${entry.msg}` : entry?.msg;
      })
      .filter(Boolean)
      .join(' ');
    if (message) return message;
  }
  return copy.required;
}

/**
 * Cash on delivery, and nothing else yet.
 *
 * COD is the whole payment story until S4 selects a gateway, and it is a
 * complete one: the order is placed, the courier collects, and
 * ``cod_collection_status`` tracks the money. Offering a card option that
 * cannot charge anything would be worse than offering none.
 */
export default function CheckoutPage() {
  const { cart, reset } = useCart();
  const { locale, href } = useLocale();
  const copy = COPY[locale] ?? COPY.en;

  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);

  const items = cart?.items ?? [];

  // Keyed on the cart token, so returning to checkout with the same basket
  // does not count as beginning again.
  useTrackOnce(items.length > 0 ? cart?.token : null, () => beginCheckout(cart, { locale }));

  const onSubmit = async (event) => {
    event.preventDefault();
    setError(null);
    const form = new FormData(event.currentTarget);

    setPending(true);
    try {
      const order = await placeOrder(
        locale,
        {
          customer: {
            email: form.get('email') || null,
            phone: form.get('phone') || null,
            first_name: form.get('first_name') || null,
            last_name: form.get('last_name') || null,
          },
          shipping_address: {
            recipient_name: form.get('recipient_name'),
            phone: form.get('phone'),
            governorate: form.get('governorate'),
            city: form.get('city'),
            street_address: form.get('street_address'),
            building: form.get('building') || null,
          },
          payment_method: 'cod',
        },
        // One key per attempt. The API refuses an order without it, and it is
        // what makes a double-click or a retry return the same order rather
        // than creating a second one.
        crypto.randomUUID(),
      );

      // Fired before the cart is cleared and before navigating, so the event
      // exists even if the shopper closes the tab on the confirmation page.
      // transaction_id is the order number, which is what de-duplicates this
      // against the server-side purchase S5 will send for the same order.
      pushEvent(purchase(order, { locale }));

      // The cart became the order. Keeping the token would show the shopper a
      // basket that has already been bought.
      clearCartToken();
      reset();
      await navigate(href(`/order/${order.order_number}`));
    } catch (failure) {
      setError(describeError(failure?.response?.data?.detail, copy));
      setPending(false);
    }
  };

  if (items.length === 0) {
    return (
      <>
        <h1>{copy.heading}</h1>
        <p>
          {copy.empty} <a href={href('/')}>{copy.keepShopping}</a>
        </p>
      </>
    );
  }

  return (
    <>
      <h1>{copy.heading}</h1>

      {error ? (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      ) : null}

      <form className={styles.layout} onSubmit={onSubmit}>
        <div className={styles.fields}>
          <fieldset>
            <legend>{copy.contact}</legend>
            <label>
              {copy.email}
              <input name="email" type="email" autoComplete="email" required />
            </label>
            <label>
              {copy.phone}
              {/* dir="ltr" on every phone and number field: an Egyptian mobile
                  number is read left-to-right even on an Arabic page. */}
              <input name="phone" type="tel" dir="ltr" autoComplete="tel" required />
            </label>
            <div className={styles.pair}>
              <label>
                {copy.firstName}
                <input name="first_name" autoComplete="given-name" />
              </label>
              <label>
                {copy.lastName}
                <input name="last_name" autoComplete="family-name" />
              </label>
            </div>
          </fieldset>

          <fieldset>
            <legend>{copy.delivery}</legend>
            <label>
              {copy.recipient}
              <input name="recipient_name" autoComplete="name" required />
            </label>
            <div className={styles.pair}>
              <label>
                {copy.governorate}
                <input name="governorate" autoComplete="address-level1" required />
              </label>
              <label>
                {copy.city}
                <input name="city" autoComplete="address-level2" required />
              </label>
            </div>
            <label>
              {copy.street}
              <input name="street_address" autoComplete="street-address" required />
            </label>
            <label>
              {copy.building}
              <input name="building" />
            </label>
          </fieldset>

          <fieldset>
            <legend>{copy.payment}</legend>
            <p className={styles.cod}>
              <strong>{copy.cod}</strong>
              <span>{copy.codNote}</span>
            </p>
          </fieldset>
        </div>

        <aside className={styles.summary}>
          <p className={styles.total}>
            <span>{copy.total}</span>
            <strong>{money(cart?.total, locale)}</strong>
          </p>
          <button type="submit" className={styles.place} disabled={pending}>
            {pending ? copy.placing : copy.place}
          </button>
        </aside>
      </form>
    </>
  );
}
