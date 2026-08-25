import { render } from 'vike/abort';

import { publicOrigin } from '../../services/api.js';
import { isLocale } from '../../utils/locales.js';

const TITLES = { en: 'Checkout — Marvel', ar: 'إتمام الطلب — مارفل' };

/** noindex, for the same reason as the cart: per-shopper, nothing to index. */
export function data(pageContext) {
  const { locale } = pageContext.routeParams;
  if (!isLocale(locale)) throw render(404);

  return {
    locale,
    head: {
      title: TITLES[locale] ?? TITLES.en,
      canonical: `${publicOrigin()}/${locale}/checkout`,
      noindex: true,
    },
  };
}
