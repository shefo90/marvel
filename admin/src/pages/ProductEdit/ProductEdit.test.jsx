import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';

import ProductEdit from './ProductEdit.jsx';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const PRODUCT = {
  id: 7,
  item_group_id: 'SUEDESANDAL-A1B2C3',
  slug: 'suede-sandal',
  title: 'Suede Sandal',
  brand: 'Pixi',
  status: 'draft',
  category_id: 3,
  description: 'Soft suede.',
  condition: 'new',
  gender: 'female',
  age_group: 'adult',
  tags: ['summer'],
  translations: [
    {
      locale: 'en',
      title: 'Suede Sandal',
      description: 'Soft suede.',
      slug: 'suede-sandal',
      meta_description: 'A soft suede sandal.',
      is_published: true,
      is_complete: true,
    },
  ],
  variants: [
    {
      id: 11,
      sku: 'SUEDESANDAL-38-BLACK',
      variant_title: '38 / black',
      size: '38',
      color: 'black',
      price: '500.00',
      sale_price: null,
      stock_quantity: 4,
      is_active: true,
    },
  ],
};

const CATEGORIES = [
  { id: 3, name: 'Sandals', slug: 'sandals', parent_id: 1, parent_name: 'Shoes', position: 1, is_active: true },
];

/** The two requests the editor always makes, plus whatever a test adds. */
function serveEditor(product = PRODUCT) {
  server.use(
    http.get('*/api/admin/products/7', () => HttpResponse.json(product)),
    http.get('*/api/admin/categories', () => HttpResponse.json(CATEGORIES)),
    http.get('*/api/admin/products/7/readiness', () => HttpResponse.json([])),
  );
}

function renderEditor() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/products/7']}>
        <Routes>
          <Route path="/products/:id" element={<ProductEdit />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it('loads every editable base field, not just the ones it can display cheaply', async () => {
  serveEditor();
  renderEditor();

  expect(await screen.findByDisplayValue('Suede Sandal')).toBeInTheDocument();
  // The trap this guards: a description that exists but renders blank, so the
  // operator believes there is none.
  expect(screen.getByDisplayValue('Soft suede.')).toBeInTheDocument();
  expect(screen.getByTitle('new')).toBeInTheDocument();
});

it('saves an edited base field', async () => {
  serveEditor();
  let body = null;
  server.use(
    http.patch('*/api/admin/products/7', async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ ...PRODUCT, title: body.title });
    }),
  );
  const user = userEvent.setup();
  renderEditor();
  const title = await screen.findByDisplayValue('Suede Sandal');

  await user.clear(title);
  await user.type(title, 'Suede Sandal II');
  await user.click(screen.getByRole('button', { name: /save/i }));

  await waitFor(() => expect(body?.title).toBe('Suede Sandal II'));
});

it('archives only after a confirmation', async () => {
  serveEditor();
  let archived = false;
  server.use(
    http.post('*/api/admin/products/7/archive', () => {
      archived = true;
      return HttpResponse.json({ ...PRODUCT, status: 'archived' });
    }),
  );
  const user = userEvent.setup();
  renderEditor();

  await user.click(await screen.findByRole('button', { name: /archive/i }));
  expect(archived).toBe(false);

  await user.click(await screen.findByRole('button', { name: /^yes, archive$/i }));

  await waitFor(() => expect(archived).toBe(true));
});
