import { fireEvent, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, beforeEach, expect, it } from 'vitest';

import { renderAt } from '../../test/render.jsx';
import Page from './+Page.jsx';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

beforeEach(() => {
  window.localStorage.clear();
  window.dataLayer = [];
});

const LINE = {
  variant_id: 42,
  sku: 'SUEDE-1-38',
  title: 'Suede Sandal',
  quantity: 2,
  unit_price_snapshot: '1299.00',
  unit_price_effective: '1299.00',
  line_total: '2598.00',
  line_discount: '0.00',
  price_changed: false,
};

const CART = {
  token: 'cart-token-1',
  status: 'open',
  locale: 'en',
  currency: 'EGP',
  item_count: 2,
  subtotal: '2598.00',
  discount_total: '0.00',
  total: '2598.00',
  items: [LINE],
};

function serveCart(cart = CART) {
  server.use(http.post('*/api/en/cart', () => HttpResponse.json(cart)));
}

it('views the cart once it loads, at the cart\'s own total', async () => {
  serveCart();
  renderAt(<Page />);

  await screen.findByText('Suede Sandal');

  // useTrackOnce fires from a useEffect, which commits a tick after the DOM
  // text findByText resolves on -- an immediate read here is a timing race,
  // not a logic one.
  await waitFor(() =>
    expect(window.dataLayer.find((entry) => entry.event === 'view_cart')).toBeDefined(),
  );
  const pushed = window.dataLayer.find((entry) => entry.event === 'view_cart');
  expect(pushed.ecommerce.value).toBe(2598);
  expect(pushed.ecommerce.items[0].item_id).toBe('SUEDE-1-38');
});

it('fires remove_from_cart for that line only when it is removed', async () => {
  serveCart();
  server.use(
    http.delete('*/api/en/cart/items/42', () =>
      HttpResponse.json({ ...CART, items: [], item_count: 0, subtotal: '0.00', total: '0.00' }),
    ),
  );
  renderAt(<Page />);

  await screen.findByText('Suede Sandal');
  fireEvent.click(screen.getByRole('button', { name: 'Remove' }));

  // Fired synchronously in the click handler, before the async removal call
  // resolves -- same rule as add_to_cart on the product page: the event
  // exists even if the request that follows it fails.
  const pushed = window.dataLayer.find((entry) => entry.event === 'remove_from_cart');
  expect(pushed).toBeDefined();
  expect(pushed.ecommerce.value).toBe(2598);
  expect(pushed.ecommerce.items[0].item_id).toBe('SUEDE-1-38');
});

it('fires remove_from_cart when quantity is set to zero, the other way a line disappears', async () => {
  // The API treats quantity: 0 on PATCH /cart/items/{id} as a removal, so this
  // is the same event as the Remove button, reached by a second path.
  serveCart();
  server.use(
    http.patch('*/api/en/cart/items/42', () =>
      HttpResponse.json({ ...CART, items: [], item_count: 0, subtotal: '0.00', total: '0.00' }),
    ),
  );
  renderAt(<Page />);

  await screen.findByText('Suede Sandal');
  fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '0' } });

  const pushed = window.dataLayer.find((entry) => entry.event === 'remove_from_cart');
  expect(pushed).toBeDefined();
  expect(pushed.ecommerce.value).toBe(2598);
});

it('does not remove the line while the quantity field is merely cleared to retype', async () => {
  // Number('') is 0 in JS. Selecting the digit and pressing Backspace before
  // typing a new quantity produces exactly this intermediate value -- it must
  // not read as "the shopper chose zero".
  serveCart();
  let patched = false;
  server.use(
    http.patch('*/api/en/cart/items/42', () => {
      patched = true;
      return HttpResponse.json(CART);
    }),
  );
  renderAt(<Page />);

  await screen.findByText('Suede Sandal');
  fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '' } });

  expect(window.dataLayer.find((entry) => entry.event === 'remove_from_cart')).toBeUndefined();
  expect(patched).toBe(false);
});
