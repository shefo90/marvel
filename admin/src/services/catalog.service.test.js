import { afterEach, expect, it, vi } from 'vitest';

import { api } from './api.js';
import { uploadImage } from './catalog.service.js';

afterEach(() => vi.restoreAllMocks());

it('puts the file and its alt text into one multipart body', async () => {
  // Asserted here rather than through a request: jsdom's XHR replaces the
  // filename with "blob" and drops the bytes, so a transport-level test cannot
  // see what this function actually built.
  const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} });
  const file = new File([new Uint8Array([137, 80, 78, 71])], 'sandal.png', {
    type: 'image/png',
  });

  await uploadImage(7, { file, altText: 'A sandal from above' });

  const [url, body] = post.mock.calls[0];
  expect(url).toBe('/admin/products/7/images');
  expect(body.get('file').name).toBe('sandal.png');
  expect(body.get('alt_text')).toBe('A sandal from above');
});

it('omits variant_id entirely when the image belongs to the product', async () => {
  // Sent as the string "null" it would be a 422: the field is int | None, and
  // "null" is neither.
  const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} });
  const file = new File([new Uint8Array([137])], 'a.png', { type: 'image/png' });

  await uploadImage(7, { file, altText: 'Alt' });

  expect(post.mock.calls[0][1].has('variant_id')).toBe(false);
});

it('sends variant_id when the image belongs to one variant', async () => {
  const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} });
  const file = new File([new Uint8Array([137])], 'a.png', { type: 'image/png' });

  await uploadImage(7, { file, altText: 'Alt', variantId: 11 });

  expect(post.mock.calls[0][1].get('variant_id')).toBe('11');
});
