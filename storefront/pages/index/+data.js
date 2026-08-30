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
      'Shoes and bags made for Egyptian summers and everything after them. Cash on delivery, nationwide.',
    heroCta: 'Shop new in',
    heroCtaAlt: 'Browse bags',
    newIn: 'New in',
    shopCategory: 'Shop by category',
    edits: 'Edits',
    viewAll: 'View all',
    shoes: 'Shoes',
    bags: 'Bags',
    promises: [
      ['Cash on delivery', 'Pay when it reaches your door.'],
      ['Nationwide delivery', 'Every governorate in Egypt.'],
      ['Easy exchanges', 'Wrong size? Swap it.'],
    ],
  },
  ar: {
    title: 'مارفل — أحذية وحقائب نسائية',
    description: 'أحذية وحقائب، توصيل داخل مصر. الدفع عند الاستلام متاح.',
    eyebrow: 'توصيل لكل المحافظات',
    heroTitle: 'كل خطوة لها حساب.',
    heroBody:
      'أحذية وحقائب لصيف مصر وما بعده. الدفع عند الاستلام، لكل المحافظات.',
    heroCta: 'تسوّقي الجديد',
    heroCtaAlt: 'تصفّحي الحقائب',
    newIn: 'وصل حديثًا',
    shopCategory: 'تسوّقي حسب القسم',
    edits: 'تشكيلات',
    viewAll: 'عرض الكل',
    shoes: 'أحذية',
    bags: 'حقائب',
    promises: [
      ['الدفع عند الاستلام', 'ادفعي عند وصول الطلب.'],
      ['توصيل لكل المحافظات', 'داخل مصر بالكامل.'],
      ['استبدال سهل', 'المقاس مش مظبوط؟ غيّريه.'],
    ],
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

  // One await, not three in sequence. These are independent reads and the page
  // cannot render until the slowest returns either way, so serialising them
  // would just add the other two latencies to it.
  const empty = { items: [], total: 0 };
  const [listing, categories, collections] = await Promise.all([
    listProducts(locale, { page: 1, pageSize: 8, sort: 'newest' }).catch(() => empty),
    listCategories(locale).catch(() => []),
    listCollections(locale).catch(() => []),
  ]);

  // "Shoes" and "bags" are two specific level-1 categories, not a concept the
  // API knows about -- the only stable way to find them from either
  // language's tree is base_slug, which (unlike slug) is never translated.
  // Once found, everything downstream uses that category's real slug for
  // *this* locale, so an Arabic slug like "أحذية" resolves instead of 404ing
  // against the English literal "shoes".
  const findByBaseSlug = (baseSlug) => categories.find((node) => node.base_slug === baseSlug);
  const shoesCategory = findByBaseSlug('shoes');
  const bagsCategory = findByBaseSlug('bags');
  const shoesSlug = shoesCategory?.slug ?? 'shoes';
  const bagsSlug = bagsCategory?.slug ?? 'bags';

  const [shoes, bags] = await Promise.all([
    shoesCategory
      ? listProducts(locale, { category: shoesSlug, pageSize: 4 }).catch(() => empty)
      : empty,
    bagsCategory
      ? listProducts(locale, { category: bagsSlug, pageSize: 4 }).catch(() => empty)
      : empty,
  ]);

  return {
    locale,
    listing,
    shoes,
    bags,
    shoesSlug,
    bagsSlug,
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
