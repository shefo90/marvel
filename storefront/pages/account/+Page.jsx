import { useEffect, useState } from 'react';

import styles from '../../assets/styles/account.module.scss';
import { useAccount } from '../../hooks/useAccount.jsx';
import { useLocale } from '../../hooks/useLocale.jsx';
import { getOrders } from '../../services/account.service.js';
import { money } from '../../utils/format.js';

const COPY = {
  en: {
    heading: 'Your account',
    orders: 'Your orders',
    none: 'You have not placed an order yet.',
    shop: 'Start shopping',
    addresses: 'Your addresses',
    signOut: 'Sign out',
    signIn: 'Sign in to see your orders.',
    toSignIn: 'Sign in',
    placed: 'Placed',
    items: 'items',
    loading: 'Loading your orders…',
  },
  ar: {
    heading: 'حسابك',
    orders: 'طلباتك',
    none: 'لم تقم بأي طلب بعد.',
    shop: 'ابدأ التسوق',
    addresses: 'عناوينك',
    signOut: 'تسجيل الخروج',
    signIn: 'سجّل الدخول لعرض طلباتك.',
    toSignIn: 'تسجيل الدخول',
    placed: 'تاريخ الطلب',
    items: 'منتجات',
    loading: 'جارٍ تحميل طلباتك…',
  },
};

const STATUS = {
  en: {
    pending: 'Pending',
    confirmed: 'Confirmed',
    shipped: 'Shipped',
    delivered: 'Delivered',
    cancelled: 'Cancelled',
    returned: 'Returned',
  },
  ar: {
    pending: 'قيد الانتظار',
    confirmed: 'مؤكد',
    shipped: 'تم الشحن',
    delivered: 'تم التوصيل',
    cancelled: 'ملغي',
    returned: 'مرتجع',
  },
};

/**
 * The shopper's own orders.
 *
 * Fetched after hydration, never on the server: this is one person's purchase
 * history, and the whole reason the account API scopes every query by
 * `customer_id` would be undone by rendering it into a cacheable response.
 *
 * The status is translated rather than shown raw. `shipped` is a database enum,
 * not a word to put in front of a shopper -- and certainly not in front of an
 * Arabic-reading one.
 */
export default function Page() {
  const { locale, href } = useLocale();
  const { shopper, ready, signOut } = useAccount();
  const copy = COPY[locale] ?? COPY.en;
  const statuses = STATUS[locale] ?? STATUS.en;

  const [orders, setOrders] = useState(null);

  useEffect(() => {
    if (!shopper) return undefined;
    let cancelled = false;
    getOrders(locale)
      .then((rows) => {
        if (!cancelled) setOrders(rows);
      })
      .catch(() => {
        if (!cancelled) setOrders([]);
      });
    return () => {
      cancelled = true;
    };
  }, [locale, shopper]);

  // `ready` is the resume attempt finishing. Rendering the signed-out view
  // before it settles would flash "sign in" at somebody who is signed in.
  if (!ready) return <div className={styles.panel} />;

  if (!shopper) {
    return (
      <div className={styles.panel}>
        <h1>{copy.heading}</h1>
        <p>{copy.signIn}</p>
        <a className={styles.primary} href={href('/account/login')}>
          {copy.toSignIn}
        </a>
      </div>
    );
  }

  return (
    <div className={styles.wide}>
      <header className={styles.header}>
        <h1>{copy.heading}</h1>
        <p className={styles.aside}>{shopper.email}</p>
        <nav className={styles.actions}>
          <a href={href('/account/addresses')}>{copy.addresses}</a>
          <button type="button" className={styles.link} onClick={signOut}>
            {copy.signOut}
          </button>
        </nav>
      </header>

      <h2>{copy.orders}</h2>

      {orders === null ? <p>{copy.loading}</p> : null}

      {orders !== null && orders.length === 0 ? (
        <>
          <p>{copy.none}</p>
          <a className={styles.primary} href={href('/')}>
            {copy.shop}
          </a>
        </>
      ) : null}

      {orders !== null && orders.length > 0 ? (
        <ul className={styles.list} aria-label={copy.orders}>
          {orders.map((order) => (
            <li key={order.order_number} className={styles.row}>
              <div>
                <strong>{order.order_number}</strong>
                <span className={styles.aside}>
                  {' '}
                  · {order.item_count} {copy.items}
                </span>
              </div>
              <div className={styles.aside}>
                {copy.placed} {order.placed_at ? order.placed_at.slice(0, 10) : '—'}
              </div>
              <div>{statuses[order.status] ?? order.status}</div>
              <div>{money(order.total, locale)}</div>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
