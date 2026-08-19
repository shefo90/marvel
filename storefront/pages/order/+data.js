import { render } from 'vike/abort';

import { publicOrigin } from '../../services/api.js';
import { isLocale } from '../../utils/locales.js';

const TITLES = { en: 'Order confirmed — Marvel', ar: 'تم تأكيد الطلب — مارفل' };

/**
 * The order is NOT fetched here.
 *
 * Looking one up requires the placing contact -- the API refuses otherwise --
 * and a server render has no shopper session to prove that with. So the page
 * confirms from what checkout already knows, and the order number is the
 * receipt. noindex, obviously: it is one person's purchase.
 */
export function data(pageContext) {
  const { locale, orderNumber } = pageContext.routeParams;
  if (!isLocale(locale)) throw render(404);

  return {
    locale,
    orderNumber,
    head: {
      title: TITLES[locale] ?? TITLES.en,
      canonical: `${publicOrigin()}/${locale}/order/${orderNumber}`,
      noindex: true,
    },
  };
}
