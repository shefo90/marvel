import { useLocale } from '../../../hooks/useLocale.jsx';
import { usePageContext } from '../../../hooks/usePageContext.jsx';
import styles from './Footer.module.scss';

const COPY = {
  en: {
    rights: 'Egypt only. Prices include VAT.',
    shop: 'Shop',
    help: 'Customer care',
    about: 'Marvel',
    blurb: 'Shoes and bags, delivered across Egypt. Cash on delivery available.',
    links: [
      ['Delivery', '/delivery'],
      ['Returns', '/returns'],
      ['Size guide', '/size-guide'],
      ['Contact', '/contact'],
    ],
  },
  ar: {
    rights: 'داخل مصر فقط. الأسعار شاملة ضريبة القيمة المضافة.',
    shop: 'المتجر',
    help: 'خدمة العملاء',
    about: 'مارفل',
    blurb: 'أحذية وحقائب، توصيل داخل مصر. الدفع عند الاستلام متاح.',
    links: [
      ['الشحن والتوصيل', '/delivery'],
      ['الإرجاع والاستبدال', '/returns'],
      ['دليل المقاسات', '/size-guide'],
      ['تواصل معنا', '/contact'],
    ],
  },
};

/**
 * The footer is the shop's other navigation.
 *
 * It carries the category tree because that is the one place a shopper who has
 * scrolled to the bottom expects to find it, and because on a phone the
 * header's hover panel is hidden — without this, the only way into a
 * subcategory on touch is through the category page itself.
 *
 * The customer-care links point at pages that do not exist yet. They are here
 * because the information architecture is the deliverable and the pages are
 * content; leaving the column out entirely would hide the gap rather than name
 * it.
 */
export default function Footer() {
  const { locale, href } = useLocale();
  const pageContext = usePageContext();
  const copy = COPY[locale] ?? COPY.en;
  const categories = pageContext?.data?.categories ?? [];

  return (
    <footer className={styles.footer}>
      <div className={styles.grid}>
        <div className={styles.brandColumn}>
          <p className={styles.brand}>{copy.about}</p>
          <p className={styles.blurb}>{copy.blurb}</p>
        </div>

        {categories.map((category) => (
          <nav key={category.id} aria-label={category.title}>
            <h2 className={styles.heading}>{category.title}</h2>
            <ul className={styles.links}>
              {category.children?.map((child) => (
                <li key={child.id}>
                  <a href={href(`/c/${child.slug}`)}>{child.title}</a>
                </li>
              ))}
            </ul>
          </nav>
        ))}

        <nav aria-label={copy.help}>
          <h2 className={styles.heading}>{copy.help}</h2>
          <ul className={styles.links}>
            {copy.links.map(([label, path]) => (
              <li key={path}>
                <a href={href(path)}>{label}</a>
              </li>
            ))}
          </ul>
        </nav>
      </div>

      {/* Prices are VAT-inclusive by design, so saying so is a statement of
          fact rather than a disclaimer -- tax_total is 0 on every order. */}
      <p className={styles.rights}>{copy.rights}</p>
    </footer>
  );
}
