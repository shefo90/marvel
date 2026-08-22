import { render } from 'vike/abort';

import { publicOrigin } from '../../services/api.js';
import { isLocale } from '../../utils/locales.js';

const COPY = {
  en: { title: 'Sign in — Marvel' },
  ar: { title: 'تسجيل الدخول — مارفل' },
};

/**
 * No data fetched, and noindex, for the same reasons as the cart.
 *
 * A sign-in form has nothing to index and every account page behind it is one
 * person's. Letting a crawler in burns budget on a URL that is either a form or
 * a redirect.
 */
export function data(pageContext) {
  const { locale } = pageContext.routeParams;
  if (!isLocale(locale)) throw render(404);

  return {
    locale,
    head: {
      title: (COPY[locale] ?? COPY.en).title,
      canonical: `${publicOrigin()}/${locale}/account/login`,
      noindex: true,
    },
  };
}
