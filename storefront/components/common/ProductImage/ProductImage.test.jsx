import { fireEvent, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, beforeAll, expect, it } from 'vitest';

import { renderAt } from '../../../test/render.jsx';
import ProductImage from './ProductImage.jsx';

// CartProvider fetches a cart on mount; nothing here cares about the result.
const server = setupServer(
  http.post('*/api/en/cart', () => HttpResponse.json({ token: 't', items: [], item_count: 0 })),
  http.get('*/api/en/cart', () => HttpResponse.json({ token: 't', items: [], item_count: 0 })),
);
beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }));
afterAll(() => server.close());

const IMAGE = {
  id: 1,
  url: '/media/aa/bb/photo-full.png',
  alt_text: 'A suede sandal',
  width: 1200,
  height: 900,
};

it('always carries the dimensions that hold the layout still', () => {
  // product_images makes width and height NOT NULL precisely so this can rely
  // on them: an <img> without them reflows the page when it loads, which is
  // the CLS budget section 8A sets.
  renderAt(<ProductImage image={IMAGE} />);

  const img = screen.getByAltText('A suede sandal');
  expect(img).toHaveAttribute('width', '1200');
  expect(img).toHaveAttribute('height', '900');
});

it('loads lazily by default and eagerly when asked', () => {
  const { unmount } = renderAt(<ProductImage image={IMAGE} />);
  expect(screen.getByAltText('A suede sandal')).toHaveAttribute('loading', 'lazy');
  unmount();

  // Lazy-loading something already in the viewport delays the largest
  // contentful paint rather than helping it.
  renderAt(<ProductImage image={IMAGE} eager />);
  expect(screen.getByAltText('A suede sandal')).toHaveAttribute('loading', 'eager');
});

it('falls back to a blank frame when the file will not load', () => {
  // A browser's broken-image icon across a product grid makes a working shop
  // look broken. The frame keeps its size, so the failure shifts nothing.
  renderAt(<ProductImage image={IMAGE} />);

  fireEvent.error(screen.getByAltText('A suede sandal'));

  expect(screen.queryByAltText('A suede sandal')).not.toBeInTheDocument();
});

it('renders the same blank frame when there is no image at all', () => {
  const { container } = renderAt(<ProductImage image={null} />);

  expect(container.querySelector('div[aria-hidden="true"]')).toBeInTheDocument();
});
