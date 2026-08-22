import { render } from 'vike/abort';

import { publicOrigin } from '../../services/api.js';
import { isLocale } from '../../utils/locales.js';

const COPY = {
  en: { title: 'Your account — Marvel' },
  ar: { title: 'حسابك — مارفل' },
};

/**
 * Nothing fetched here, and noindex.
 *
 * Everything on this page belongs to one shopper and is loaded in the browser
 * after hydration. A server-rendered copy would be a page a cache could hand to
 * somebody else, and a crawlable one would be a URL that is never twice the
 * same.
 */
export function data(pageContext) {
  const { locale } = pageContext.routeParams;
  if (!isLocale(locale)) throw render(404);

  return {
    locale,
    head: {
      title: (COPY[locale] ?? COPY.en).title,
      canonical: `${publicOrigin()}/${locale}/account`,
      noindex: true,
    },
  };
}
