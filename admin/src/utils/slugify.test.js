import { expect, it } from 'vitest';

import { slugify } from './slugify.js';

it('lower-cases and joins words with single hyphens', () => {
  expect(slugify('Suede Sandal')).toBe('suede-sandal');
});

it('collapses whitespace, punctuation and repeated hyphens', () => {
  expect(slugify('  Suede   Sandal!! ')).toBe('suede-sandal');
  expect(slugify('summer--sale')).toBe('summer-sale');
});

it('folds diacritics rather than dropping the letter', () => {
  // "Café" must not become "caf". The base slug is ASCII by constraint, but an
  // accented letter still has an obvious ASCII counterpart.
  expect(slugify('Café Crème')).toBe('cafe-creme');
});

it('returns nothing for a title with no ASCII letters', () => {
  // ck_products_slug_format is ASCII-only, and the base slug is not the Arabic
  // one -- that lives on the translation. An empty result asks the operator to
  // type a slug instead of inventing a wrong one.
  expect(slugify('صندل جلد')).toBe('');
});

it('never returns a leading or trailing hyphen', () => {
  // The pattern is ^[a-z0-9]+(-[a-z0-9]+)*$ -- an edge hyphen is a 400.
  expect(slugify('-Sandal-')).toBe('sandal');
  expect(slugify('...Sandal...')).toBe('sandal');
});
