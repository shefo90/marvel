import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';

import ProductNew from './ProductNew.jsx';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const CATEGORIES = [
  { id: 3, name: 'Sandals', slug: 'sandals', parent_id: 1, parent_name: 'Shoes', position: 1, is_active: true },
  { id: 4, name: 'Clutches', slug: 'clutches', parent_id: 2, parent_name: 'Bags', position: 1, is_active: true },
];

function serveCategories() {
  server.use(http.get('*/api/admin/categories', () => HttpResponse.json(CATEGORIES)));
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/products/new']}>
        <Routes>
          <Route path="/products/new" element={<ProductNew />} />
          <Route path="/products/:id" element={<div>editor opened</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it('fills the slug in from the title, and leaves it editable', async () => {
  serveCategories();
  const user = userEvent.setup();
  renderPage();

  await user.type(screen.getByLabelText(/^title/i), 'Suede Sandal');

  expect(screen.getByLabelText(/^slug/i)).toHaveValue('suede-sandal');

  await user.clear(screen.getByLabelText(/^slug/i));
  await user.type(screen.getByLabelText(/^slug/i), 'summer-sandal');
  expect(screen.getByLabelText(/^slug/i)).toHaveValue('summer-sandal');
});

it('stops overwriting the slug once it has been edited by hand', async () => {
  // Otherwise a late correction to the title silently discards the slug the
  // operator chose -- and the slug is the URL, which cannot be quietly changed
  // after publication without a redirect.
  serveCategories();
  const user = userEvent.setup();
  renderPage();

  await user.type(screen.getByLabelText(/^title/i), 'Suede Sandal');
  await user.clear(screen.getByLabelText(/^slug/i));
  await user.type(screen.getByLabelText(/^slug/i), 'chosen-by-hand');
  await user.type(screen.getByLabelText(/^title/i), ' Mark II');

  expect(screen.getByLabelText(/^slug/i)).toHaveValue('chosen-by-hand');
});

it('offers the level-2 categories the API returned', async () => {
  serveCategories();
  const user = userEvent.setup();
  renderPage();

  await user.click(screen.getByLabelText(/category/i));

  expect(await screen.findByTitle(/Sandals/)).toBeInTheDocument();
  expect(screen.getByTitle(/Clutches/)).toBeInTheDocument();
});

it('opens the editor once the product exists', async () => {
  serveCategories();
  server.use(
    http.post('*/api/admin/products', () =>
      HttpResponse.json({ id: 7, slug: 'suede-sandal' }, { status: 201 }),
    ),
  );
  const user = userEvent.setup();
  renderPage();

  await user.type(screen.getByLabelText(/^title/i), 'Suede Sandal');
  await user.click(screen.getByLabelText(/category/i));
  await user.click(await screen.findByTitle(/Sandals/));
  await user.click(screen.getByRole('button', { name: /create/i }));

  expect(await screen.findByText('editor opened')).toBeInTheDocument();
});

it('puts a slug conflict on the slug field rather than in a toast', async () => {
  // 409 detail is a plain string. Shown as a floating message it tells the
  // operator a slug is taken without saying which field to fix.
  serveCategories();
  server.use(
    http.post('*/api/admin/products', () =>
      HttpResponse.json({ detail: 'slug already in use' }, { status: 409 }),
    ),
  );
  const user = userEvent.setup();
  renderPage();

  await user.type(screen.getByLabelText(/^title/i), 'Suede Sandal');
  await user.click(screen.getByLabelText(/category/i));
  await user.click(await screen.findByTitle(/Sandals/));
  await user.click(screen.getByRole('button', { name: /create/i }));

  await waitFor(() => {
    const field = screen.getByLabelText(/^slug/i).closest('.ant-form-item');
    expect(within(field).getByText('slug already in use')).toBeInTheDocument();
  });
});
