import { screen } from '@testing-library/react';
import { expect, it } from 'vitest';

import { renderAt } from '../../../test/render.jsx';
import ProductCard from './ProductCard.jsx';

const PRODUCT = {
  id: 7,
  slug: 'suede-sandal',
  title: 'Suede Sandal',
  brand: 'Pixi',
  price: '500.00',
  sale_price: null,
  primary_image: {
    url: '/media/aa/bb/photo-full.png',
    alt_text: 'A suede sandal',
    width: 1200,
    height: 900,
  },
};

it('links to the product in the language being read', () => {
  renderAt(<ProductCard product={PRODUCT} />, { locale: 'ar', pathname: '/ar' });

  expect(screen.getByRole('link')).toHaveAttribute('href', '/ar/products/suede-sandal');
});

it('loads the first card eagerly and later ones lazily', () => {
  const { unmount } = renderAt(<ProductCard product={PRODUCT} index={0} />);
  expect(screen.getByAltText('A suede sandal')).toHaveAttribute('loading', 'eager');
  unmount();

  renderAt(<ProductCard product={PRODUCT} index={9} />);
  expect(screen.getByAltText('A suede sandal')).toHaveAttribute('loading', 'lazy');
});

it('shows a markdown as two prices, the old one struck through', () => {
  renderAt(<ProductCard product={{ ...PRODUCT, sale_price: '400.00' }} />);

  // <s>, not a CSS line-through: a screen reader announces it as no longer
  // current rather than reading two prices with no relationship.
  const struck = screen.getByText((_, node) => node.tagName === 'S');
  expect(struck).toBeInTheDocument();
});
