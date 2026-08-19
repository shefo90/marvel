import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter } from 'react-router-dom';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';

import Promotions from './Promotions.jsx';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const EID = {
  id: 3,
  name: 'Eid 20% off sandals',
  type: 'percentage',
  discount_percent: '20.00',
  discount_amount: null,
  buy_quantity: null,
  get_quantity: null,
  get_discount_percent: null,
  starts_at: null,
  ends_at: null,
  is_active: true,
  targets: [{ id: 9, target_type: 'category', target_id: 4 }],
};

const CATEGORIES = [
  { id: 4, name: 'Sandals', slug: 'sandals', parent_id: 1, parent_name: 'Shoes', position: 1, is_active: true },
];

function serve(promotions = [EID]) {
  server.use(
    http.get('*/api/admin/promotions', () => HttpResponse.json(promotions)),
    http.get('*/api/admin/categories', () => HttpResponse.json(CATEGORIES)),
  );
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Promotions />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it('lists each offer with what it does', async () => {
  serve();
  renderPage();

  expect(await screen.findByText('Eid 20% off sandals')).toBeInTheDocument();
  expect(screen.getByText('20%')).toBeInTheDocument();
});

it('says what an offer applies to, not just that it has targets', async () => {
  // "1 target" tells the operator nothing they can act on.
  serve();
  renderPage();
  const row = (await screen.findByText('Eid 20% off sandals')).closest('tr');

  expect(within(row).getByText(/Shoes \/ Sandals/)).toBeInTheDocument();
});

it('shows an offer with no window as running until it is turned off', async () => {
  serve();
  renderPage();
  const row = (await screen.findByText('Eid 20% off sandals')).closest('tr');

  expect(within(row).getByText(/always on/i)).toBeInTheDocument();
});

it('pauses an offer without touching its dates', async () => {
  let body = null;
  serve();
  server.use(
    http.patch('*/api/admin/promotions/3', async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ ...EID, is_active: false });
    }),
  );
  const user = userEvent.setup();
  renderPage();
  const row = (await screen.findByText('Eid 20% off sandals')).closest('tr');

  await user.click(within(row).getByRole('button', { name: /pause/i }));

  await waitFor(() => expect(body).toEqual({ is_active: false }));
});

it('offers the BOGO fields only for a BOGO promotion', async () => {
  serve();
  const user = userEvent.setup();
  renderPage();

  await user.click(await screen.findByRole('button', { name: /new offer/i }));
  const dialog = await screen.findByRole('dialog');
  expect(within(dialog).queryByLabelText(/buy quantity/i)).not.toBeInTheDocument();

  await user.click(within(dialog).getByLabelText(/type/i));
  await user.click(await screen.findByTitle('bogo'));

  expect(await within(dialog).findByLabelText(/buy quantity/i)).toBeInTheDocument();
  expect(within(dialog).queryByLabelText(/discount percent/i)).not.toBeInTheDocument();
});

it('creates a percentage offer targeting the whole catalogue', async () => {
  let body = null;
  serve();
  server.use(
    http.post('*/api/admin/promotions', async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ ...EID, id: 11 }, { status: 201 });
    }),
  );
  const user = userEvent.setup();
  renderPage();

  await user.click(await screen.findByRole('button', { name: /new offer/i }));
  const dialog = await screen.findByRole('dialog');
  await user.type(within(dialog).getByLabelText(/name/i), 'Summer sale');
  await user.type(within(dialog).getByLabelText(/discount percent/i), '25');
  await user.click(within(dialog).getByRole('button', { name: /create offer/i }));

  await waitFor(() => expect(body).not.toBeNull());
  expect(body.name).toBe('Summer sale');
  expect(body.type).toBe('percentage');
  expect(body.targets).toEqual([{ target_type: 'all', target_id: null }]);
});

it('shows the reason the API refused an offer', async () => {
  serve();
  server.use(
    http.post('*/api/admin/promotions', () =>
      HttpResponse.json(
        { detail: 'the end of the window must be after its start' },
        { status: 422 },
      ),
    ),
  );
  const user = userEvent.setup();
  renderPage();

  await user.click(await screen.findByRole('button', { name: /new offer/i }));
  const dialog = await screen.findByRole('dialog');
  await user.type(within(dialog).getByLabelText(/name/i), 'Bad window');
  await user.type(within(dialog).getByLabelText(/discount percent/i), '25');
  await user.click(within(dialog).getByRole('button', { name: /create offer/i }));

  expect(
    await screen.findByText('the end of the window must be after its start'),
  ).toBeInTheDocument();
});
