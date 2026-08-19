import { useData } from '../../hooks/useData.js';
import { useLocale } from '../../hooks/useLocale.jsx';
import styles from './order.module.scss';

const COPY = {
  en: {
    heading: 'Thank you — your order is confirmed',
    numberLabel: 'Your order number',
    note: 'Keep this number. You will need it to ask about your order.',
    cod: 'Pay the courier in cash when your order arrives.',
    keepShopping: 'Continue shopping',
  },
  ar: {
    heading: 'شكرًا لك — تم تأكيد طلبك',
    numberLabel: 'رقم طلبك',
    note: 'احتفظ بهذا الرقم. ستحتاجه للسؤال عن طلبك.',
    cod: 'ادفع نقدًا لمندوب التوصيل عند وصول طلبك.',
    keepShopping: 'متابعة التسوق',
  },
};

/**
 * The receipt.
 *
 * Deliberately a confirmation rather than a lookup: fetching the order would
 * need the placing contact, which this page has no way to prove it holds. The
 * order number is what the shopper needs, and it is already in the URL.
 */
export default function OrderPage() {
  const { orderNumber } = useData();
  const { locale, href } = useLocale();
  const copy = COPY[locale] ?? COPY.en;

  return (
    <div className={styles.panel}>
      <h1>{copy.heading}</h1>

      <p>{copy.numberLabel}</p>
      <p className={styles.number}>{orderNumber}</p>

      <p className={styles.note}>{copy.note}</p>
      <p className={styles.note}>{copy.cod}</p>

      <a className={styles.keepShopping} href={href('/')}>
        {copy.keepShopping}
      </a>
    </div>
  );
}
