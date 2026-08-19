import { DEFAULT_LOCALE } from './locales.js';

/**
 * Money, in EGP, with Latin digits in both languages.
 *
 * Section 6.6 requires Western digits for prices, sizes, quantities, order IDs
 * and SKUs in BOTH locales, and ar-EG defaults to Arabic-Indic — so the
 * numbering system is forced rather than left to the locale. The same rule is
 * why formatted numerals never reach analytics: dataLayer values carry raw
 * numbers.
 *
 * Egypt and EGP only, a locked decision, so there is no currency argument.
 */
export function money(amount, locale = DEFAULT_LOCALE) {
  const value = Number(amount ?? 0);
  return new Intl.NumberFormat(locale === 'ar' ? 'ar-EG' : 'en-EG', {
    style: 'currency',
    currency: 'EGP',
    minimumFractionDigits: 2,
    numberingSystem: 'latn',
  }).format(value);
}

/** Two prices when there is a markdown, one when there is not. */
export function priceParts(price, salePrice) {
  const hasMarkdown = salePrice != null && Number(salePrice) < Number(price);
  return {
    now: hasMarkdown ? salePrice : price,
    was: hasMarkdown ? price : null,
    hasMarkdown,
  };
}
