import { render } from 'vike/abort';

import { listProducts } from '../../services/catalog.service.js';
import { publicOrigin } from '../../services/api.js';
import { isLocale } from '../../utils/locales.js';

const COPY = {
  en: {
    title: 'Marvel — women’s footwear and handbags',
    description:
      'Shoes and bags, delivered across Egypt. Cash on delivery available.',
    heading: 'New in',
  },
  ar: {
    title: 'مارفل — أحذية وحقائب نسائية',
    description: 'أحذية وحقائب، توصيل داخل مصر. الدفع عند الاستلام متاح.',
    heading: 'وصل حديثًا',
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

  let listing = { items: [], total: 0 };
  try {
    listing = await listProducts(locale, { page: 1, pageSize: 24 });
  } catch {
    // A catalogue that will not load is an empty shop, not a broken one. The
    // page still renders its chrome and its head, so a crawler sees a valid
    // document rather than a 500.
  }

  return {
    locale,
    listing,
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
