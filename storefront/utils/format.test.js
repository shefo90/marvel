import { expect, it } from 'vitest';

import { money, priceParts } from './format.js';

it('prices in EGP', () => {
  expect(money('500.00', 'en')).toContain('500');
  expect(money('500.00', 'en')).toMatch(/EGP|E£/);
});

it('uses Arabic digits for an Arabic reader', () => {
  // An Egyptian reading the Arabic page expects ٥٠٠, not 500.
  expect(money('500.00', 'ar')).toMatch(/[٠-٩]/);
});

it('shows both prices only when there is a real markdown', () => {
  expect(priceParts('500.00', '400.00')).toMatchObject({ now: '400.00', was: '500.00' });
  expect(priceParts('500.00', null).was).toBeNull();
});

it('ignores a sale price that is not actually lower', () => {
  // A "sale" at the same price is not a sale, and striking through an
  // identical number is a lie the shopper can see.
  expect(priceParts('500.00', '500.00').hasMarkdown).toBe(false);
});
