import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';

import ContentTab from './ContentTab.jsx';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const PRODUCT = {
  id: 7,
  title: 'Suede Sandal',
  slug: 'suede-sandal',
  status: 'draft',
  translations: [
    {
      locale: 'en',
      title: 'Suede Sandal',
      description: 'Soft suede.',
      slug: 'suede-sandal',
      meta_description: 'A soft suede sandal.',
      seo_title: null,
      og_title: null,
      og_description: null,
      og_image_url: null,
      image_alt: null,
      is_published: true,
      is_complete: true,
    },
    {
      locale: 'ar',
      title: 'صندل',
      description: null,
      slug: 'صندل',
      meta_description: null,
      seo_title: null,
      og_title: null,
      og_description: null,
      og_image_url: null,
      image_alt: null,
      is_published: false,
      is_complete: false,
    },
  ],
  variants: [{ id: 11, sku: 'X-38-BLACK', is_active: true }],
};

function serveReadiness(blockers = []) {
  server.use(
    http.get('*/api/admin/products/7/readiness', () => HttpResponse.json(blockers)),
  );
}

function renderTab(product = PRODUCT) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ContentTab product={product} />
    </QueryClientProvider>,
  );
}

it('edits one language at a time, starting with English', async () => {
  serveReadiness();
  renderTab();

  expect(await screen.findByDisplayValue('Suede Sandal')).toBeInTheDocument();
  expect(screen.queryByDisplayValue('صندل')).not.toBeInTheDocument();
});

it('switches to the other language without losing which one is shown', async () => {
  serveReadiness();
  const user = userEvent.setup();
  renderTab();
  await screen.findByDisplayValue('Suede Sandal');

  // The hidden input carries pointer-events: none; a person clicks the label.
  await user.click(screen.getByText('Arabic'));

  // By field, not by value: the Arabic title and slug happen to be the same
  // string, so a bare display-value query matches both.
  expect(await screen.findByLabelText(/^title/i)).toHaveValue('صندل');
});

it('marks the Arabic fields right-to-left', async () => {
  // Text direction inside a textbox, not RTL chrome: the interface stays
  // English, but Arabic content typed into a left-to-right box is unreadable.
  serveReadiness();
  const user = userEvent.setup();
  renderTab();
  await screen.findByDisplayValue('Suede Sandal');

  // The hidden input carries pointer-events: none; a person clicks the label.
  await user.click(screen.getByText('Arabic'));

  expect(await screen.findByLabelText(/^title/i)).toHaveAttribute('dir', 'rtl');
});

it('saves the language being edited', async () => {
  serveReadiness();
  let body = null;
  let path = null;
  server.use(
    http.put('*/api/admin/products/7/translations/:locale', async ({ request, params }) => {
      body = await request.json();
      path = params.locale;
      return HttpResponse.json({ ...PRODUCT.translations[0], title: body.title });
    }),
  );
  const user = userEvent.setup();
  renderTab();
  const title = await screen.findByDisplayValue('Suede Sandal');

  await user.clear(title);
  await user.type(title, 'Suede Sandal II');
  await user.click(screen.getByRole('button', { name: /save english/i }));

  await waitFor(() => expect(body?.title).toBe('Suede Sandal II'));
  expect(path).toBe('en');
});

it('shows what still blocks this language before publishing is attempted', async () => {
  serveReadiness([
    { code: 'no_variant', message: 'Add at least one variant before publishing.' },
  ]);
  renderTab();

  expect(
    await screen.findByText('Add at least one variant before publishing.'),
  ).toBeInTheDocument();
});

it('renders the blocker list the publish call refuses with', async () => {
  // 422 detail is a list of {code, message}. Rendered as a toast it would be
  // "[object Object]", which is precisely the shape the API went to the trouble
  // of returning structured data to avoid.
  serveReadiness();
  server.use(
    http.post('*/api/admin/products/7/publish', () =>
      HttpResponse.json(
        {
          detail: [
            { code: 'incomplete_translation', message: 'ar needs: description, meta description' },
          ],
        },
        { status: 422 },
      ),
    ),
  );
  const user = userEvent.setup();
  renderTab();
  await screen.findByDisplayValue('Suede Sandal');

  await user.click(screen.getByText('Arabic'));
  await user.click(await screen.findByRole('button', { name: /publish arabic/i }));

  expect(
    await screen.findByText('ar needs: description, meta description'),
  ).toBeInTheDocument();
});
