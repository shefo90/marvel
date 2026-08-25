import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, expect, it, vi } from 'vitest';

import VariantsTab from './VariantsTab.jsx';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  vi.unstubAllGlobals();
});
afterAll(() => server.close());

// The role gate is the subject of one test, so it is injected rather than
// driven through a real login: this file is about the variants table.
const auth = vi.hoisted(() => ({ canSetCost: false }));
vi.mock('../../hooks/useAuth.js', () => ({ useAuth: () => auth }));

const PRODUCT = {
  id: 7,
  item_group_id: 'SUEDE-A1B2C3',
  variants: [
    {
      id: 11,
      sku: 'SUEDE-A1B2C3-38-BLACK',
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

function renderTab(product = PRODUCT) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <VariantsTab product={product} />
    </QueryClientProvider>,
  );
}

it('shows each variant, and says the SKU cannot be changed later', async () => {
  // trg_variants_sku_immutable makes a typo permanent, and Merchant Center and
  // the Meta catalog both key on it. Saying so at entry beats surfacing a
  // restrict_violation afterwards.
  auth.canSetCost = false;
  renderTab();

  expect(screen.getByText('SUEDE-A1B2C3-38-BLACK')).toBeInTheDocument();
  expect(screen.getByText(/immutable/i)).toBeInTheDocument();
});

it('generates the size by colour matrix on the server', async () => {
  auth.canSetCost = false;
  let body = null;
  server.use(
    http.post('*/api/admin/products/7/variants', async ({ request }) => {
      body = await request.json();
      return HttpResponse.json([], { status: 201 });
    }),
  );
  const user = userEvent.setup();
  renderTab();

  await user.type(screen.getByLabelText(/sizes/i), '38,39,');
  await user.type(screen.getByLabelText(/colours/i), 'black,');
  await user.clear(screen.getByLabelText(/^price/i));
  await user.type(screen.getByLabelText(/^price/i), '500');
  await user.click(screen.getByRole('button', { name: /generate/i }));

  await waitFor(() => expect(body).not.toBeNull());
  expect(body.sizes).toEqual(['38', '39']);
  expect(body.colors).toEqual(['black']);
  expect(String(body.price)).toBe('500');
});

it('saves an edited variant', async () => {
  auth.canSetCost = false;
  let body = null;
  server.use(
    http.patch('*/api/admin/variants/11', async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ ...PRODUCT.variants[0], ...body });
    }),
  );
  const user = userEvent.setup();
  renderTab();

  await user.click(screen.getByRole('button', { name: /edit/i }));
  // Scoped to the dialog: the matrix form above the table has a Stock field too.
  const dialog = await screen.findByRole('dialog');
  const stock = within(dialog).getByLabelText(/stock/i);
  await user.clear(stock);
  await user.type(stock, '12');
  await user.click(screen.getByRole('button', { name: /^save variant$/i }));

  await waitFor(() => expect(body?.stock_quantity).toBe(12));
});

it('offers the cost field to an admin only', async () => {
  auth.canSetCost = false;
  const user = userEvent.setup();
  const { unmount } = renderTab();

  await user.click(screen.getByRole('button', { name: /edit/i }));
  const catalogDialog = await screen.findByRole('dialog');
  expect(within(catalogDialog).queryByLabelText(/cost/i)).not.toBeInTheDocument();
  unmount();

  auth.canSetCost = true;
  renderTab();
  await user.click(screen.getByRole('button', { name: /edit/i }));

  const adminDialog = await screen.findByRole('dialog');
  expect(within(adminDialog).getByLabelText(/cost/i)).toBeInTheDocument();
});
