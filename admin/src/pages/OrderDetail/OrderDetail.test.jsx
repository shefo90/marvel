import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';

import OrderDetail from './OrderDetail.jsx';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const ORDER = {
  order_id: 1,
  order_number: 'ORD-1357',
  status: 'pending',
  payment_status: 'pending',
  payment_method: 'cod',
  cod_collection_status: 'pending',
  locale: 'en',
  currency: 'EGP',
  subtotal: '1299.00',
  discount: '0.00',
  shipping: '0.00',
  tax_total: '0.00',
  total: '1299.00',
  promotion_cost_total: '0.00',
  refunded_amount_total: '0.00',
  customer_email: 'shopper@example.com',
  customer_phone: '01001234567',
  placed_at: '2026-08-19T10:00:00Z',
  items: [
    {
      line_number: 1,
      sku: 'PX-SANDAL-01-BLA-37',
      product_title: 'Leather Strap Sandal',
      variant_label: '37 / black',
      quantity: 1,
      unit_list_price: '1299.00',
      unit_price: '1299.00',
      discount_amount: '0.00',
      discount_source: null,
      line_total: '1299.00',
      refunded_quantity: 0,
    },
  ],
  status_history: [],
};

function serve(order = ORDER) {
  server.use(http.get('*/api/admin/orders/ORD-1357', () => HttpResponse.json(order)));
}

function renderDetail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/orders/ORD-1357']}>
        <Routes>
          <Route path="/orders/:orderNumber" element={<OrderDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it('shows the order, its money and its lines', async () => {
  serve();
  renderDetail();

  expect(await screen.findByText('ORD-1357')).toBeInTheDocument();
  expect(screen.getByText('PX-SANDAL-01-BLA-37')).toBeInTheDocument();
  expect(screen.getByText('shopper@example.com')).toBeInTheDocument();
});

it('offers only the moves the API will accept', async () => {
  // A button that comes back 409 teaches the operator to distrust the screen.
  serve();
  renderDetail();
  await screen.findByText('ORD-1357');

  expect(screen.getByRole('button', { name: /mark confirmed/i })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /mark cancelled/i })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /mark shipped/i })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /mark delivered/i })).not.toBeInTheDocument();
});

it('offers nothing further on a cancelled order', async () => {
  // Cancelled is terminal. Anything after it is a new order or a refund.
  serve({ ...ORDER, status: 'cancelled' });
  renderDetail();
  await screen.findByText('ORD-1357');

  expect(screen.queryByRole('button', { name: /^mark /i })).not.toBeInTheDocument();
});

it('sends the new status and the reason together', async () => {
  serve();
  let body = null;
  server.use(
    http.patch('*/api/admin/orders/ORD-1357/status', async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ ...ORDER, status: 'confirmed' });
    }),
  );
  const user = userEvent.setup();
  renderDetail();
  await screen.findByText('ORD-1357');

  await user.click(screen.getByRole('button', { name: /mark confirmed/i }));
  const dialog = await screen.findByRole('dialog');
  await user.type(within(dialog).getByLabelText(/reason/i), 'Stock checked');
  await user.click(within(dialog).getByRole('button', { name: /mark confirmed/i }));

  await waitFor(() => expect(body).toEqual({ status: 'confirmed', reason: 'Stock checked' }));
});

it('shows who moved the order and when', async () => {
  // order_status_history exists so that question has an answer. Rendering only
  // the current status would waste it.
  serve({
    ...ORDER,
    status: 'confirmed',
    status_history: [
      {
        dimension: 'order',
        from_status: 'pending',
        to_status: 'confirmed',
        actor_type: 'staff',
        actor_user_id: 42,
        reason: 'Stock checked',
        created_at: '2026-08-19T11:00:00Z',
      },
    ],
  });
  renderDetail();

  expect(await screen.findByText(/pending → confirmed/)).toBeInTheDocument();
  expect(screen.getByText('Stock checked')).toBeInTheDocument();
  expect(screen.getByText(/staff #42/)).toBeInTheDocument();
});
