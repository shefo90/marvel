import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter } from 'react-router-dom';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';

import Collections from './Collections.jsx';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const SUMMER = {
  id: 2,
  name: 'Summer Edit',
  slug: 'summer-edit',
  list_id: 'summer_edit',
  description: 'Warm weather picks',
  position: 1,
  is_active: true,
  product_count: 3,
  updated_at: '2026-08-21T09:00:00+00:00',
  translations: [],
};

const PRODUCTS = [
  { id: 7, slug: 'suede-sandal', title: 'Suede Sandal', brand: 'Pixi', status: 'active', variant_count: 4, image_count: 2, translations: [] },
  { id: 8, slug: 'leather-mule', title: 'Leather Mule', brand: 'Pixi', status: 'active', variant_count: 2, image_count: 1, translations: [] },
  { id: 9, slug: 'canvas-flat', title: 'Canvas Flat', brand: 'Pixi', status: 'active', variant_count: 3, image_count: 1, translations: [] },
];

function serve(collections = [SUMMER], extra = []) {
  server.use(
    http.get('*/api/admin/taxonomy/collections', () => HttpResponse.json(collections)),
    http.get('*/api/admin/products', () =>
      HttpResponse.json({ items: PRODUCTS, page: 1, page_size: 50, total: PRODUCTS.length }),
    ),
    ...extra,
  );
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Collections />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it('lists each collection with how many products it holds', async () => {
  serve();
  renderPage();

  expect(await screen.findByText('Summer Edit')).toBeInTheDocument();
  expect(screen.getByText('3')).toBeInTheDocument();
});

it('keeps an inactive collection visible and flags it', async () => {
  serve([{ ...SUMMER, is_active: false }]);
  renderPage();

  expect(await screen.findByText('Summer Edit')).toBeInTheDocument();
  expect(screen.getByText('hidden')).toBeInTheDocument();
});

it('creates a collection', async () => {
  let posted = null;
  serve([SUMMER], [
    http.post('*/api/admin/taxonomy/collections', async ({ request }) => {
      posted = await request.json();
      return HttpResponse.json({ ...SUMMER, id: 5, name: 'Eid Edit' }, { status: 201 });
    }),
  ]);
  const user = userEvent.setup();
  renderPage();
  await screen.findByText('Summer Edit');

  await user.click(screen.getByRole('button', { name: 'New collection' }));
  await user.type(await screen.findByLabelText('Name'), 'Eid Edit');
  await user.click(screen.getByRole('button', { name: 'Create collection' }));

  await waitFor(() => expect(posted).not.toBeNull());
  expect(posted.name).toBe('Eid Edit');
});

it('sends the version it was shown when hiding a collection', async () => {
  let patched = null;
  serve([SUMMER], [
    http.patch('*/api/admin/taxonomy/collections/2', async ({ request }) => {
      patched = await request.json();
      return HttpResponse.json({ ...SUMMER, is_active: false });
    }),
  ]);
  const user = userEvent.setup();
  renderPage();
  await screen.findByText('Summer Edit');

  await user.click(screen.getAllByRole('button', { name: 'Hide' })[0]);

  await waitFor(() => expect(patched).not.toBeNull());
  expect(patched.expected_updated_at).toBe('2026-08-21T09:00:00+00:00');
});

it('offers no way to delete a collection', async () => {
  // item_list_id is stamped onto historic cart and order lines.
  serve();
  renderPage();
  await screen.findByText('Summer Edit');

  expect(screen.queryByRole('button', { name: /delete/i })).not.toBeInTheDocument();
});

// --- membership ----------------------------------------------------------

function serveMembership(productIds = [8, 7], extra = []) {
  return serve([SUMMER], [
    http.get('*/api/admin/taxonomy/collections/2/products', () =>
      HttpResponse.json({ product_ids: productIds }),
    ),
    ...extra,
  ]);
}

it('shows the members in the order the collection holds them', async () => {
  // The order is the data: it drives the featured sort and section 5's index.
  // Alphabetical or id order would silently misreport what the shopper sees.
  serveMembership([8, 7]);
  const user = userEvent.setup();
  renderPage();
  await screen.findByText('Summer Edit');

  await user.click(screen.getAllByRole('button', { name: 'Products' })[0]);

  const members = await screen.findByRole('list', { name: 'Products in this collection' });
  const names = within(members).getAllByRole('listitem').map((row) => row.textContent);
  expect(names[0]).toContain('Leather Mule');
  expect(names[1]).toContain('Suede Sandal');
});

it('saves the whole membership in order after a move', async () => {
  let put = null;
  serveMembership([8, 7], [
    http.put('*/api/admin/taxonomy/collections/2/products', async ({ request }) => {
      put = await request.json();
      return HttpResponse.json({ product_ids: [7, 8] });
    }),
  ]);
  const user = userEvent.setup();
  renderPage();
  await screen.findByText('Summer Edit');

  await user.click(screen.getAllByRole('button', { name: 'Products' })[0]);
  await screen.findByRole('list', { name: 'Products in this collection' });
  await user.click(screen.getByRole('button', { name: 'Move Suede Sandal up' }));
  await user.click(screen.getByRole('button', { name: 'Save order' }));

  await waitFor(() => expect(put).not.toBeNull());
  expect(put.product_ids).toEqual([7, 8]);
});

it('adds a product to the collection', async () => {
  let put = null;
  serveMembership([8], [
    http.put('*/api/admin/taxonomy/collections/2/products', async ({ request }) => {
      put = await request.json();
      return HttpResponse.json({ product_ids: [8, 9] });
    }),
  ]);
  const user = userEvent.setup();
  renderPage();
  await screen.findByText('Summer Edit');

  await user.click(screen.getAllByRole('button', { name: 'Products' })[0]);
  await screen.findByRole('list', { name: 'Products in this collection' });
  await user.click(screen.getByRole('button', { name: 'Add Canvas Flat' }));
  await user.click(screen.getByRole('button', { name: 'Save order' }));

  await waitFor(() => expect(put).not.toBeNull());
  expect(put.product_ids).toEqual([8, 9]);
});

it('removes a product from the collection', async () => {
  let put = null;
  serveMembership([8, 7], [
    http.put('*/api/admin/taxonomy/collections/2/products', async ({ request }) => {
      put = await request.json();
      return HttpResponse.json({ product_ids: [8] });
    }),
  ]);
  const user = userEvent.setup();
  renderPage();
  await screen.findByText('Summer Edit');

  await user.click(screen.getAllByRole('button', { name: 'Products' })[0]);
  await screen.findByRole('list', { name: 'Products in this collection' });
  await user.click(screen.getByRole('button', { name: 'Remove Suede Sandal' }));
  await user.click(screen.getByRole('button', { name: 'Save order' }));

  await waitFor(() => expect(put).not.toBeNull());
  expect(put.product_ids).toEqual([8]);
});
