import { expect, it } from 'vitest';

import { isLocale, splitLocale, withLocale } from './locales.js';

it('accepts only the two languages that exist', () => {
  // Section 8A: "/ar-eg/, /AR/, /arabic/ return 404 unless present in an
  // explicit alias map." There is no alias map.
  expect(isLocale('en')).toBe(true);
  expect(isLocale('ar')).toBe(true);
  expect(isLocale('ar-eg')).toBe(false);
  expect(isLocale('AR')).toBe(false);
  expect(isLocale('arabic')).toBe(false);
});

it('reports no locale for a path that has none, rather than guessing one', () => {
  // Guessing is how a page ends up served at two addresses.
  expect(splitLocale('/products/sandal').locale).toBeNull();
});

it('splits a localised path into its language and the rest', () => {
  expect(splitLocale('/ar/products/sandal')).toEqual({
    locale: 'ar',
    rest: '/products/sandal',
  });
});

it('swaps the language without touching the rest of the path', () => {
  expect(withLocale('/en/products/suede-sandal', 'ar')).toBe('/ar/products/suede-sandal');
});

it('keeps the home page tidy when swapping language', () => {
  expect(withLocale('/en', 'ar')).toBe('/ar');
});
