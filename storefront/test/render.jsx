import { render } from '@testing-library/react';

import { AccountProvider } from '../hooks/useAccount.jsx';
import { CartProvider } from '../hooks/useCart.jsx';
import { LocaleProvider } from '../hooks/useLocale.jsx';
import { PageContextProvider } from '../hooks/usePageContext.jsx';

/**
 * Render a component the way the app does.
 *
 * The providers are not optional scaffolding — locale decides every link in the
 * tree, so a component rendered without one is not the component the shopper
 * sees.
 */
export function renderAt(ui, { locale = 'en', pathname = '/en', data = {} } = {}) {
  const pageContext = { data: { locale, ...data }, urlPathname: pathname, routeParams: { locale } };

  return render(
    <PageContextProvider pageContext={pageContext}>
      <LocaleProvider locale={locale} pathname={pathname}>
        <AccountProvider>
          <CartProvider>{ui}</CartProvider>
        </AccountProvider>
      </LocaleProvider>
    </PageContextProvider>,
  );
}
