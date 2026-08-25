import { render } from 'vike/abort';

import { publicOrigin } from '../../services/api.js';
import { isLocale } from '../../utils/locales.js';

const COPY = {
  en: { title: 'Your cart — Marvel' },
  ar: { title: 'سلتك — مارفل' },
};

/**
 * No data is fetched here, and that is the point.
 *
 * The cart belongs to one shopper and is loaded in the browser. This exists
 * only to establish the locale and to mark the page noindex: a cart has nothing
 * to index and differs for every visitor, so listing it burns crawl budget on
 * a URL that is never the same twice.
 */
export function data(pageContext) {
  const { locale } = pageContext.routeParams;
  if (!isLocale(locale)) throw render(404);

  return {
    locale,
    head: {
      title: (COPY[locale] ?? COPY.en).title,
      canonical: `${publicOrigin()}/${locale}/cart`,
      noindex: true,
    },
  };
}
