import { useLocale } from '../../../hooks/useLocale.jsx';
import styles from './Footer.module.scss';

const COPY = {
  en: { rights: 'Egypt only. Prices include VAT.' },
  ar: { rights: 'داخل مصر فقط. الأسعار شاملة ضريبة القيمة المضافة.' },
};

export default function Footer() {
  const { locale } = useLocale();
  return (
    <footer className={styles.footer}>
      {/* Prices are VAT-inclusive by design, so saying so is a statement of
          fact rather than a disclaimer -- tax_total is 0 on every order. */}
      <p>{(COPY[locale] ?? COPY.en).rights}</p>
    </footer>
  );
}
