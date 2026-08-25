import { expect, it } from 'vitest';

import { buildHead, productJsonLd } from './head.js';

const BOTH = {
  en: 'https://marvel.com/en/products/suede-sandal',
  ar: 'https://marvel.com/ar/products/صندل',
};

it('emits an absolute canonical', () => {
  // A relative canonical is ignored, and naming one address out of several is
  // the entire job.
  const head = buildHead({ canonical: 'https://marvel.com/en/products/x' });

  expect(head).toContain('<link rel="canonical" href="https://marvel.com/en/products/x"/>');
});

it('emits reciprocal hreflang for a real cluster', () => {
  const head = buildHead({ alternates: BOTH });

  expect(head).toContain('hreflang="en"');
  expect(head).toContain('hreflang="ar"');
});

it('emits no hreflang at all for a cluster of one', () => {
  // A page pointing only at itself tells a crawler nothing.
  const head = buildHead({ alternates: { en: BOTH.en } });

  expect(head).not.toContain('hreflang');
});

it('names English as x-default', () => {
  const head = buildHead({ alternates: BOTH });

  expect(head).toContain('hreflang="x-default"');
});

it('marks per-shopper pages noindex', () => {
  const head = buildHead({ title: 'Cart', noindex: true });

  expect(head).toContain('name="robots" content="noindex, nofollow"');
});

it('escapes a title that contains markup', () => {
  const head = buildHead({ title: 'Sandal <script>alert(1)</script>' });

  expect(head).not.toContain('<script>alert(1)</script>');
  expect(head).toContain('&lt;script&gt;');
});

it('neutralises a closing script tag inside JSON-LD', () => {
  // A product description containing "</script>" would otherwise end the block
  // early and drop raw markup into the page.
  const head = buildHead({ jsonLd: { name: 'Sandal </script><img src=x>' } });

  expect(head).not.toContain('</script><img');
});

it('describes a product with its price and availability', () => {
  const product = {
    title: 'Suede Sandal',
    brand: 'Pixi',
    item_group_id: 'SUEDE-1',
    images: [{ url: '/media/a.png', is_primary: true }],
    variants: [
      { sku: 'S-38', price: '500.00', sale_price: null, currency: 'EGP', availability: 'in_stock' },
    ],
  };

  const jsonLd = productJsonLd(product, { canonical: BOTH.en, locale: 'en' });

  expect(jsonLd['@type']).toBe('Product');
  expect(jsonLd.offers.price).toBe('500.00');
  expect(jsonLd.offers.availability).toBe('https://schema.org/InStock');
});

it('advertises the price actually asked, not the list price', () => {
  // Section 8 flags a mismatch between structured data and the page as a
  // Merchant diagnostic, so the marked-down price is the one published.
  const product = {
    title: 'Suede Sandal', brand: 'Pixi', item_group_id: 'S-1',
    variants: [{ sku: 'S-38', price: '500.00', sale_price: '400.00', currency: 'EGP', availability: 'in_stock' }],
  };

  const jsonLd = productJsonLd(product, { canonical: BOTH.en, locale: 'en' });

  expect(jsonLd.offers.price).toBe('400.00');
});

it('reports an out-of-stock product as out of stock', () => {
  const product = {
    title: 'Gone', brand: 'Pixi', item_group_id: 'G-1',
    variants: [{ sku: 'G-38', price: '500.00', currency: 'EGP', availability: 'out_of_stock' }],
  };

  const jsonLd = productJsonLd(product, { canonical: BOTH.en, locale: 'en' });

  expect(jsonLd.offers.availability).toBe('https://schema.org/OutOfStock');
});
