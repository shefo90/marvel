import { screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';

import { renderAt } from '../../../test/render.jsx';
import Header from './Header.jsx';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function serveCart(cart = { token: 't', items: [], item_count: 0 }) {
  server.use(
    http.post('*/api/:locale/cart', () => HttpResponse.json(cart)),
    http.get('*/api/:locale/cart', () => HttpResponse.json(cart)),
  );
}

it('offers the other language as a link, not a toggle', async () => {
  // It changes the URL, and the URL is the only thing that decides language.
  // A JavaScript toggle would leave two languages at one address -- the
  // duplicate-content problem section 8A exists to prevent -- and a crawler
  // would never see the second one.
  serveCart();
  renderAt(<Header />, { locale: 'en', pathname: '/en/products/suede-sandal' });

  const link = screen.getByRole('link', { name: 'العربية' });
  expect(link).toHaveAttribute('href', '/ar/products/suede-sandal');
  expect(link).toHaveAttribute('hreflang', 'ar');
});

it('does not link the language already being read', async () => {
  serveCart();
  renderAt(<Header />, { locale: 'ar', pathname: '/ar' });

  expect(screen.queryByRole('link', { name: 'العربية' })).not.toBeInTheDocument();
  expect(screen.getByText('العربية')).toHaveAttribute('aria-current', 'true');
});

it('keeps every link inside the language being read', async () => {
  serveCart();
  renderAt(<Header />, { locale: 'ar', pathname: '/ar' });

  // A hardcoded "/cart" would drop an Arabic shopper into the English site,
  // and would do it only on the pages nobody tested in Arabic.
  expect(screen.getByRole('link', { name: /السلة/ })).toHaveAttribute('href', '/ar/cart');
});

it('shows how many items are waiting once the cart loads', async () => {
  serveCart({ token: 't', items: [{ variant_id: 1 }], item_count: 3 });
  renderAt(<Header />);

  expect(await screen.findByText('3')).toBeInTheDocument();
});

it('shows no count at all for an empty cart', async () => {
  // A "0" badge is visual noise that tells the shopper nothing.
  serveCart();
  renderAt(<Header />);

  expect(screen.queryByText('0')).not.toBeInTheDocument();
});

it('makes switching language a full navigation, not a client-side re-render', async () => {
  // Section 6.7: locale switching is a full navigation, and the server owns
  // <html lang/dir>. rel="external" is what keeps Vike's client router out of
  // the link -- without it the document would keep the previous language's
  // direction while showing the other language's words.
  serveCart();
  renderAt(<Header />, { locale: 'en', pathname: '/en' });

  expect(screen.getByRole('link', { name: 'العربية' })).toHaveAttribute('rel', 'external');
});
