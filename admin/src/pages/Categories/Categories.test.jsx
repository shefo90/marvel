import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter } from 'react-router-dom';
import { afterAll, afterEach, beforeAll, expect, it, vi } from 'vitest';

import Categories from './Categories.jsx';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const SANDALS = {
  id: 4,
  parent_id: 1,
  level: 2,
  name: 'Sandals',
  slug: 'sandals',
  list_id: 'cat_sandals',
  position: 1,
  is_active: true,
  product_count: 12,
  updated_at: '2026-08-21T10:00:00+00:00',
  translations: [],
  children: [],
};

const SHOES = {
  id: 1,
  parent_id: null,
  level: 1,
  name: 'Shoes',
  slug: 'shoes',
  list_id: 'cat_shoes',
  position: 1,
  is_active: true,
  product_count: 0,
  updated_at: '2026-08-21T09:00:00+00:00',
  translations: [],
  children: [SANDALS],
};

function serve(tree = [SHOES], extra = []) {
  server.use(
    http.get('*/api/admin/taxonomy/categories', () => HttpResponse.json(tree)),
    ...extra,
  );
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Categories />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it('shows a child category under its parent', async () => {
  serve();
  renderPage();

  expect(await screen.findByText('Shoes')).toBeInTheDocument();
  expect(screen.getByText('Sandals')).toBeInTheDocument();
});

it('shows how many products a category holds', async () => {
  // The operator is about to deactivate things. What deactivating hides is the
  // number they need, and it is the reason the API reports product_count.
  serve();
  renderPage();

  expect(await screen.findByText('12')).toBeInTheDocument();
});

it('keeps an inactive category visible and flags it', async () => {
  // A category that vanishes from its own editor reads as deleted, and nothing
  // here deletes.
  serve([{ ...SHOES, is_active: false, children: [] }]);
  renderPage();

  expect(await screen.findByText('Shoes')).toBeInTheDocument();
  expect(screen.getByText('hidden')).toBeInTheDocument();
});

it('creates a child under the parent that was chosen', async () => {
  let posted = null;
  serve([SHOES], [
    http.post('*/api/admin/taxonomy/categories', async ({ request }) => {
      posted = await request.json();
      return HttpResponse.json({ ...SANDALS, id: 99 }, { status: 201 });
    }),
  ]);
  const user = userEvent.setup();
  renderPage();
  await screen.findByText('Shoes');

  await user.click(screen.getByRole('button', { name: 'New category' }));
  await user.type(await screen.findByLabelText('Name'), 'Boots');
  await user.click(screen.getByLabelText('Parent'));
  await user.click(await screen.findByTitle('Shoes'));
  await user.click(screen.getByRole('button', { name: 'Create category' }));

  await waitFor(() => expect(posted).not.toBeNull());
  expect(posted.name).toBe('Boots');
  expect(posted.parent_id).toBe(1);
});

it('sends the version it was shown when deactivating', async () => {
  // The whole point of the guard: a screen that does not send the version it
  // rendered silently overwrites whoever saved in between.
  let patched = null;
  serve([SHOES], [
    http.patch('*/api/admin/taxonomy/categories/1', async ({ request }) => {
      patched = await request.json();
      return HttpResponse.json({ ...SHOES, is_active: false });
    }),
  ]);
  const user = userEvent.setup();
  renderPage();
  await screen.findByText('Shoes');

  await user.click(screen.getAllByRole('button', { name: 'Hide' })[0]);

  await waitFor(() => expect(patched).not.toBeNull());
  expect(patched.is_active).toBe(false);
  expect(patched.expected_updated_at).toBe('2026-08-21T09:00:00+00:00');
});

it('shows the conflict when someone else saved first', async () => {
  serve([SHOES], [
    http.patch('*/api/admin/taxonomy/categories/1', () =>
      HttpResponse.json(
        {
          detail:
            'this category was changed by someone else while you were editing it — reload to see their version, then reapply your change',
        },
        { status: 409 },
      ),
    ),
  ]);
  const user = userEvent.setup();
  renderPage();
  await screen.findByText('Shoes');

  await user.click(screen.getAllByRole('button', { name: 'Hide' })[0]);

  expect(await screen.findByText(/changed by someone else/)).toBeInTheDocument();
});

it('renames a category through the edit form', async () => {
  let patched = null;
  serve([SHOES], [
    http.patch('*/api/admin/taxonomy/categories/1', async ({ request }) => {
      patched = await request.json();
      return HttpResponse.json({ ...SHOES, name: 'Footwear' });
    }),
  ]);
  const user = userEvent.setup();
  renderPage();
  await screen.findByText('Shoes');

  await user.click(screen.getAllByRole('button', { name: 'Edit' })[0]);
  const name = await screen.findByLabelText('Name');
  await user.clear(name);
  await user.type(name, 'Footwear');
  await user.click(screen.getByRole('button', { name: 'Save changes' }));

  await waitFor(() => expect(patched).not.toBeNull());
  expect(patched.name).toBe('Footwear');
  expect(patched.expected_updated_at).toBe('2026-08-21T09:00:00+00:00');
});

it('offers no way to delete a category', async () => {
  // Products point at it and historic order lines carry its item_list_id.
  // is_active is the switch; a delete button would be a promise the schema
  // cannot keep.
  serve();
  renderPage();
  await screen.findByText('Shoes');

  expect(screen.queryByRole('button', { name: /delete/i })).not.toBeInTheDocument();
});

it('saves a translation against the category and locale that are showing', async () => {
  let put = null;
  let putUrl = null;
  serve([SHOES], [
    http.put('*/api/admin/taxonomy/categories/1/translations/:locale', async ({ request }) => {
      put = await request.json();
      putUrl = request.url;
      return HttpResponse.json({ locale: 'ar', title: 'أحذية', slug: 'ahzia' });
    }),
  ]);
  const user = userEvent.setup();
  renderPage();
  await screen.findByText('Shoes');

  await user.click(screen.getAllByRole('button', { name: 'Languages' })[0]);
  // The hidden input carries pointer-events: none; a person clicks the label.
  await user.click(await screen.findByText('Arabic'));
  await user.type(screen.getByLabelText('Title'), 'أحذية');
  await user.click(screen.getByRole('button', { name: 'Save Arabic' }));

  await waitFor(() => expect(put).not.toBeNull());
  expect(putUrl).toContain('/categories/1/translations/ar');
  expect(put.title).toBe('أحذية');
});
