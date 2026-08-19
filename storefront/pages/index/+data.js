import { render } from 'vike/abort';

import {
  listCategories,
  listCollections,
  listProducts,
} from '../../services/catalog.service.js';
import { publicOrigin } from '../../services/api.js';
import { isLocale } from '../../utils/locales.js';

const COPY = {
  en: {
    title: 'Marvel — women’s footwear and handbags',
    description:
      'Shoes and bags, delivered across Egypt. Cash on delivery available.',
    eyebrow: 'Delivered across Egypt',
    heroTitle: 'Every step, considered.',
    heroBody:
      'Shoes and bags made for Egyptian summers and everything after them. Delivered nationwide, cash on delivery.',
    heroCta: 'Shop new in',
    newIn: 'New in',
    shopCategory: 'Shop by category',
    edits: 'Edits',
    viewAll: 'View all',
  },
  ar: {
    title: 'مارفل — أحذية وحقائب نسائية',
    description: 'أحذية وحقائب، توصيل داخل مصر. الدفع عند الاستلام متاح.',
    eyebrow: 'توصيل لكل المحافظات',
    heroTitle: 'كل خطوة لها حساب.',
    heroBody:
      'أحذية وحقائب لصيف مصر وما بعده. توصيل لكل المحافظات، والدفع عند الاستلام.',
    heroCta: 'تسوّقي الجديد',
    newIn: 'وصل حديثًا',
    shopCategory: 'تسوّقي حسب القسم',
    edits: 'تشكيلات',
    viewAll: 'عرض الكل',
  },
};

export async function data(pageContext) {
  const { locale } = pageContext.routeParams;
  // An unrecognised locale is a 404, never a redirect and never a rendered
  // page: serving content at /arabic/ with HTTP 200 is the soft 404 section 8A
  // forbids.
  if (!isLocale(locale)) throw render(404);

  const copy = COPY[locale];
  const origin = publicOrigin();

  // One await, not four in sequence. These are independent reads and the page
  // cannot render until the slowest returns either way, so serialising them
  // would just add the other three latencies to it.
  const [listing, categories, collections] = await Promise.all([
    listProducts(locale, { page: 1, pageSize: 8, sort: 'newest' }).catch(() => ({
      items: [],
      total: 0,
    })),
    listCategories(locale).catch(() => []),
    listCollections(locale).catch(() => []),
  ]);

  return {
    locale,
    listing,
    categories,
    collections,
    copy,
    head: {
      title: copy.title,
      description: copy.description,
      canonical: `${origin}/${locale}`,
      // Both home pages always exist, so the cluster is always real.
      alternates: { en: `${origin}/en`, ar: `${origin}/ar` },
      ogType: 'website',
    },
  };
}
