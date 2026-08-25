import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter } from 'react-router-dom';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';

import Products from './Products.jsx';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const SANDAL = {
  id: 7,
  slug: 'suede-sandal',
  title: 'Suede Sandal',
  brand: 'Pixi',
  status: 'draft',
  variant_count: 4,
  image_count: 0,
  translations: [
    { locale: 'en', is_published: true, is_complete: true },
    // is_complete true, is_published false -- the row a naive UI would call
    // "ready". is_complete omits title from its generated expression, so it
    // cannot mean publishable.
    { locale: 'ar', is_published: false, is_complete: true },
  ],
};

/** Records every request the page makes, so assertions can be about the URL. */
function serveListing(items = [SANDAL], total = items.length) {
  const urls = [];
  server.use(
    http.get('*/api/admin/products', ({ request }) => {
      const url = new URL(request.url);
      urls.push(url);
      return HttpResponse.json({
        items,
        page: Number(url.searchParams.get('page') ?? 1),
        page_size: Number(url.searchParams.get('page_size') ?? 50),
        total,
      });
    }),
  );
  return urls;
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Products />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it('shows a row per product', async () => {
  serveListing();
  renderPage();

  expect(await screen.findByText('Suede Sandal')).toBeInTheDocument();
  expect(screen.getByText('suede-sandal')).toBeInTheDocument();
});

it('reports each language as published or draft, never as ready', async () => {
  serveListing();
  renderPage();
  const row = (await screen.findByText('Suede Sandal')).closest('tr');

  expect(within(row).getByTestId('locale-en')).toHaveTextContent(/published/i);
  expect(within(row).getByTestId('locale-ar')).toHaveTextContent(/draft/i);
  expect(within(row).queryByText(/ready/i)).not.toBeInTheDocument();
});

it('asks the server for the next page rather than slicing in the browser', async () => {
  const urls = serveListing([SANDAL], 120);
  const user = userEvent.setup();
  renderPage();
  await screen.findByText('Suede Sandal');

  await user.click(screen.getByTitle('2'));

  await waitFor(() => expect(urls.at(-1).searchParams.get('page')).toBe('2'));
});

it('filters by lifecycle status on the server', async () => {
  const urls = serveListing();
  const user = userEvent.setup();
  renderPage();
  await screen.findByText('Suede Sandal');

  await user.click(screen.getByLabelText(/status/i));
  await user.click(await screen.findByTitle('archived'));

  await waitFor(() => expect(urls.at(-1).searchParams.get('status')).toBe('archived'));
});

it('debounces the search box into one request', async () => {
  // Four keystrokes must not be four listings. Without the debounce the
  // operator's own typing races itself and an earlier response can land last.
  const urls = serveListing();
  const user = userEvent.setup();
  renderPage();
  await screen.findByText('Suede Sandal');
  const before = urls.length;

  await user.type(screen.getByPlaceholderText(/search/i), 'sand');

  await waitFor(() => expect(urls.at(-1).searchParams.get('search')).toBe('sand'));
  expect(urls.length - before).toBe(1);
});
