import { screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, beforeEach, expect, it } from 'vitest';

import { __resetSession } from '../../services/account.service.js';
import { renderAt } from '../../test/render.jsx';
import Page from './+Page.jsx';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }));
afterEach(() => {
  server.resetHandlers();
  __resetSession();
});
afterAll(() => server.close());

beforeEach(() => {
  document.cookie = 'marvel_csrf=csrf-value; path=/';
});

const ORDER = {
  order_number: 'MRV-2026-0007',
  status: 'shipped',
  payment_status: 'pending',
  payment_method: 'cod',
  currency: 'EGP',
  total: '850.00',
  placed_at: '2026-08-20T10:30:00+00:00',
  business_date: '2026-08-20',
  item_count: 3,
};

function serveSignedIn(orders = [ORDER]) {
  server.use(
    http.post('*/api/en/account/session/refresh', () =>
      HttpResponse.json({ access_token: 'access-1', csrf_token: 'csrf-value' }),
    ),
    http.get('*/api/en/account/me', () =>
      HttpResponse.json({ email: 'nour@example.com', orders_count: orders.length }),
    ),
    http.get('*/api/en/account/orders', () => HttpResponse.json(orders)),
  );
}

function serveSignedOut() {
  server.use(
    http.post('*/api/en/account/session/refresh', () => new HttpResponse(null, { status: 401 })),
  );
}

it('asks an anonymous visitor to sign in', async () => {
  serveSignedOut();
  renderAt(<Page />);

  expect(await screen.findByRole('link', { name: 'Sign in' })).toBeInTheDocument();
});

it('does not flash the signed-out view at a signed-in shopper', async () => {
  // The resume request settles a tick after mount. Rendering "sign in" before
  // it does would greet a returning shopper by telling them they are not.
  serveSignedIn();
  renderAt(<Page />);

  expect(screen.queryByRole('link', { name: 'Sign in' })).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByText('nour@example.com')).toBeInTheDocument());
});

it('lists the orders the shopper has placed', async () => {
  serveSignedIn();
  renderAt(<Page />);

  const list = await screen.findByRole('list', { name: 'Your orders' });
  expect(within(list).getByText('MRV-2026-0007')).toBeInTheDocument();
});

it('translates the order status rather than showing the database value', async () => {
  // `shipped` is an enum, not a word to put in front of a shopper.
  serveSignedIn();
  renderAt(<Page />);

  expect(await screen.findByText('Shipped')).toBeInTheDocument();
  expect(screen.queryByText('shipped')).not.toBeInTheDocument();
});

it('translates the status into Arabic too', async () => {
  server.use(
    http.post('*/api/ar/account/session/refresh', () =>
      HttpResponse.json({ access_token: 'access-1', csrf_token: 'csrf-value' }),
    ),
    http.get('*/api/ar/account/me', () => HttpResponse.json({ email: 'nour@example.com' })),
    http.get('*/api/ar/account/orders', () => HttpResponse.json([ORDER])),
  );
  renderAt(<Page />, { locale: 'ar', pathname: '/ar/account' });

  expect(await screen.findByText('تم الشحن')).toBeInTheDocument();
});

it('says so plainly when there are no orders yet', async () => {
  serveSignedIn([]);
  renderAt(<Page />);

  expect(await screen.findByText('You have not placed an order yet.')).toBeInTheDocument();
});
