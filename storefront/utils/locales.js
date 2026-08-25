/**
 * The two languages, and what each implies.
 *
 * The URL is the only thing that decides language — section 8A forbids
 * resolving it by IP or by Accept-Language, because a crawler and a shopper
 * must get the same page from the same address. Everything here is derived
 * from a path segment and nothing else.
 */
export const LOCALES = {
  en: { code: 'en', hreflang: 'en', dir: 'ltr', label: 'English', native: 'English' },
  ar: { code: 'ar', hreflang: 'ar', dir: 'rtl', label: 'Arabic', native: 'العربية' },
};

export const LOCALE_CODES = Object.keys(LOCALES);
export const DEFAULT_LOCALE = 'en';

export function isLocale(value) {
  return Object.prototype.hasOwnProperty.call(LOCALES, value);
}

export function localeOf(value) {
  return LOCALES[value] ?? LOCALES[DEFAULT_LOCALE];
}

/**
 * Split "/ar/products/sandal" into its locale and the rest.
 *
 * Returns `locale: null` for a path with no valid locale segment. The caller
 * decides what that means — for a page it is a 404, because serving content at
 * an unrecognised locale is the soft 404 the spec forbids.
 */
export function splitLocale(pathname) {
  const [, first, ...rest] = pathname.split('/');
  if (!isLocale(first)) return { locale: null, rest: pathname };
  return { locale: first, rest: '/' + rest.join('/') };
}

/** The same page in another language, when we know only the path. */
export function withLocale(pathname, locale) {
  const { rest } = splitLocale(pathname);
  const tail = rest === '/' ? '' : rest;
  return `/${locale}${tail}`;
}
