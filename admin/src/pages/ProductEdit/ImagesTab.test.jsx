import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';

import ImagesTab from './ImagesTab.jsx';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const PRODUCT = {
  id: 7,
  images: [
    {
      id: 21,
      url: '/media/aa/bb/aabbcc-full.png',
      alt_text: 'A suede sandal from the side',
      width: 800,
      height: 600,
      is_primary: true,
      position: 0,
      variant_id: null,
    },
    {
      id: 22,
      url: '/media/cc/dd/ccddee-full.png',
      alt_text: 'The sole',
      width: 800,
      height: 600,
      is_primary: false,
      position: 1,
      variant_id: null,
    },
  ],
};

function renderTab(product = PRODUCT) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ImagesTab product={product} />
    </QueryClientProvider>,
  );
}

function pngFile(name = 'photo.png') {
  return new File([new Uint8Array([137, 80, 78, 71])], name, { type: 'image/png' });
}

it('shows every image with the alt text as its accessible name', async () => {
  // The alt text is the point of the field. Rendering it as a caption but not
  // as alt would defeat the constraint that makes it required.
  renderTab();

  expect(screen.getByAltText('A suede sandal from the side')).toBeInTheDocument();
  expect(screen.getByAltText('The sole')).toBeInTheDocument();
});

it('marks which image is the primary one', async () => {
  renderTab();

  const primary = screen.getByAltText('A suede sandal from the side').closest('figure');
  expect(within(primary).getByText(/primary/i)).toBeInTheDocument();
});

it('will not upload without alt text', async () => {
  // The database refuses blank alt text, so the API answers 422. Asking here
  // means the operator is told before the upload, not after it.
  const user = userEvent.setup();
  renderTab();

  await user.upload(screen.getByLabelText(/choose an image/i), pngFile());
  await user.click(screen.getByRole('button', { name: /^upload$/i }));

  expect(await screen.findByText(/alt text is required/i)).toBeInTheDocument();
});

it('uploads the file and its alt text together', async () => {
  let sent = null;
  server.use(
    http.post('*/api/admin/products/7/images', async ({ request }) => {
      // Read as text, not formData(): jsdom's XHR replaces the filename with
      // "blob" and drops the bytes, so only the raw body shows the truth here --
      // that a file part and an alt_text part travel together in one request.
      // That the File keeps its identity is asserted in catalog.service.test.js,
      // where no transport is in the way.
      sent = await request.text();
      return HttpResponse.json({ ...PRODUCT.images[0], id: 23 }, { status: 201 });
    }),
  );
  const user = userEvent.setup();
  renderTab();

  await user.upload(screen.getByLabelText(/choose an image/i), pngFile('sandal.png'));
  await user.type(screen.getByLabelText(/alt text/i), 'A sandal from above');
  await user.click(screen.getByRole('button', { name: /^upload$/i }));

  await waitFor(() => expect(sent).not.toBeNull());
  expect(sent).toContain('name=\"file\"');
  expect(sent).toContain('A sandal from above');
});

it('surfaces a rejected upload as the reason the API gave', async () => {
  server.use(
    http.post('*/api/admin/products/7/images', () =>
      HttpResponse.json(
        { detail: 'the file is not a JPEG, PNG or WebP image' },
        { status: 422 },
      ),
    ),
  );
  const user = userEvent.setup();
  renderTab();

  await user.upload(screen.getByLabelText(/choose an image/i), pngFile('logo.svg'));
  await user.type(screen.getByLabelText(/alt text/i), 'A logo');
  await user.click(screen.getByRole('button', { name: /^upload$/i }));

  expect(
    await screen.findByText('the file is not a JPEG, PNG or WebP image'),
  ).toBeInTheDocument();
});

it('promotes an image to primary', async () => {
  let promoted = null;
  server.use(
    http.patch('*/api/admin/images/:id/primary', ({ params }) => {
      promoted = params.id;
      return HttpResponse.json({ ...PRODUCT.images[1], is_primary: true });
    }),
  );
  const user = userEvent.setup();
  renderTab();
  const second = screen.getByAltText('The sole').closest('figure');

  await user.click(within(second).getByRole('button', { name: /make primary/i }));

  await waitFor(() => expect(promoted).toBe('22'));
});

it('sends the whole new order when an image moves', async () => {
  // The API refuses a partial list, because the omitted rows would keep
  // positions the new ones collide with.
  let body = null;
  server.use(
    http.put('*/api/admin/products/7/images/order', async ({ request }) => {
      body = await request.json();
      return HttpResponse.json([]);
    }),
  );
  const user = userEvent.setup();
  renderTab();
  const second = screen.getByAltText('The sole').closest('figure');

  await user.click(within(second).getByRole('button', { name: /move earlier/i }));

  await waitFor(() => expect(body).not.toBeNull());
  expect(body.image_ids).toEqual([22, 21]);
});

it('deletes only after a confirmation', async () => {
  let deleted = false;
  server.use(
    http.delete('*/api/admin/images/22', () => {
      deleted = true;
      return new HttpResponse(null, { status: 204 });
    }),
  );
  const user = userEvent.setup();
  renderTab();
  const second = screen.getByAltText('The sole').closest('figure');

  await user.click(within(second).getByRole('button', { name: /delete/i }));
  expect(deleted).toBe(false);

  await user.click(await screen.findByRole('button', { name: /^yes, delete$/i }));

  await waitFor(() => expect(deleted).toBe(true));
});

it('saves Arabic alt text for one image', async () => {
  let sent = null;
  server.use(
    http.put('*/api/admin/images/21/alt/ar', async ({ request }) => {
      sent = await request.json();
      return HttpResponse.json({ locale: 'ar', alt_text: sent.alt_text });
    }),
  );
  const user = userEvent.setup();
  renderTab();
  const first = screen.getByAltText('A suede sandal from the side').closest('figure');

  await user.click(within(first).getByRole('button', { name: /arabic alt/i }));
  const dialog = await screen.findByRole('dialog');
  await user.type(within(dialog).getByLabelText(/alt text/i), 'صندل جلد');
  await user.click(within(dialog).getByRole('button', { name: /save/i }));

  await waitFor(() => expect(sent?.alt_text).toBe('صندل جلد'));
});
