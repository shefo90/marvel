import { DEFAULT_LOCALE } from './locales.js';

/**
 * Money, in EGP, in the reader's language.
 *
 * Egypt and EGP only — a locked decision, not a placeholder — so there is no
 * currency argument. Arabic gets Arabic-Indic digits from Intl, which is what
 * an Egyptian reader expects to see on a price.
 */
export function money(amount, locale = DEFAULT_LOCALE) {
  const value = Number(amount ?? 0);
  return new Intl.NumberFormat(locale === 'ar' ? 'ar-EG' : 'en-EG', {
    style: 'currency',
    currency: 'EGP',
    minimumFractionDigits: 2,
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
