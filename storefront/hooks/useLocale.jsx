import { createContext, useContext, useMemo } from 'react';

import { localeOf, withLocale } from '../utils/locales.js';

/**
 * The current language, and how to build links in it.
 *
 * Every internal link in this app goes through ``href()``. A hardcoded "/cart"
 * would silently drop an Arabic shopper into the English site — and would do it
 * only on the pages nobody tested in Arabic.
 */
const LocaleContext = createContext(null);

export function LocaleProvider({ locale, pathname, children }) {
  const value = useMemo(() => {
    const entry = localeOf(locale);
    return {
      locale: entry.code,
      dir: entry.dir,
      isRtl: entry.dir === 'rtl',
      pathname,
      href: (path) => `/${entry.code}${path === '/' ? '' : path}`,
      switchTo: (other) => withLocale(pathname, other),
    };
  }, [locale, pathname]);

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale() {
  const value = useContext(LocaleContext);
  if (value === null) {
    throw new Error('useLocale must be used inside a LocaleProvider');
  }
  return value;
}
