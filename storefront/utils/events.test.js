import { expect, it } from 'vitest';

import { addToCart, beginCheckout, purchase, toItem, viewItem, viewItemList } from './events.js';

const PRODUCT = {
  slug: 'suede-sandal',
  title: 'Suede Sandal',
  brand: 'Pixi',
  item_group_id: 'SUEDE-1',
  price: '1299.00',
  sale_price: null,
  // The listing API returns the cheapest variant's SKU under `sku`. This
  // fixture said `default_variant_sku`, which the listing does not return — so
  // the test passed while every real list impression went out with no item_id
  // at all. Caught by reading a real dataLayer in a browser, not here.
  sku: 'SUEDE-1-38',
};

const VARIANT = {
  sku: 'SUEDE-1-38',
  size: '38',
  price: '1299.00',
  sale_price: null,
  currency: 'EGP',
};

it('identifies an item by its SKU', () => {
  // Section 2: the SKU is the sellable identifier and the same value GA4 and
  // Ads use. A database id here silently breaks every join between analytics,
  // Merchant Center and the Meta catalogue.
  expect(toItem(VARIANT).item_id).toBe('SUEDE-1-38');
});

it('sends raw numbers, never formatted ones', () => {
  // Section 6.6: formatted numerals must never reach analytics. "EGP 1,299.00"
  // parses to zero, and does it silently on every order.
  const item = toItem(VARIANT);

  expect(item.price).toBe(1299);
  expect(typeof item.price).toBe('number');
});

it('reports the price actually charged, not the list price', () => {
  const item = toItem({ ...VARIANT, price: '1299.00', sale_price: '999.00' });

  expect(item.price).toBe(999);
});

it('carries list attribution on every row of a listing', () => {
  // Section 5: item_list_id and item_list_name are carried from the listing all
  // the way to order_items. If they are not on the event, the journey cannot be
  // reconstructed later.
  const event = viewItemList([PRODUCT], {
    listId: 'new_in',
    listName: 'New in',
    locale: 'en',
  });

  expect(event.event).toBe('view_item_list');
  expect(event.items[0].item_list_id).toBe('new_in');
  expect(event.items[0].index).toBe(0);
  expect(event.items[0].item_id).toBe('SUEDE-1-38');
});

it('values a product view at the price of the variant being viewed', () => {
  const event = viewItem(PRODUCT, VARIANT, { locale: 'en' });

  expect(event.value).toBe(1299);
  expect(event.currency).toBe('EGP');
  expect(event.items[0].item_variant).toBe('38');
});

it('multiplies quantity into the add_to_cart value', () => {
  const event = addToCart(PRODUCT, VARIANT, { quantity: 3, locale: 'en' });

  expect(event.value).toBe(3897);
  expect(event.items[0].quantity).toBe(3);
});

it('checks out at the total the shopper was shown', () => {
  // The cart's own total, promotions included -- re-deriving it here would
  // produce a second pricing implementation, which is the defect
  // repositories/pricing.py exists to prevent.
  const event = beginCheckout(
    {
      total: '2078.40',
      items: [
        { sku: 'SUEDE-1-38', title: 'Suede Sandal', unit_price_effective: '1299.00', quantity: 2 },
      ],
    },
    { locale: 'en' },
  );

  expect(event.value).toBe(2078.4);
  expect(event.items[0].quantity).toBe(2);
});

it('uses the order number as the transaction id', () => {
  // Section 2: the immutable commerce identity, and what de-duplicates this
  // purchase against the server-side event S5 will send for the same order.
  const event = purchase(
    {
      order_number: 'ORD-1357',
      currency: 'EGP',
      total: '1299.00',
      shipping: '0.00',
      tax_total: '0.00',
      items: [
        {
          sku: 'SUEDE-1-38',
          product_title: 'Suede Sandal',
          brand: 'Pixi',
          item_group_id: 'SUEDE-1',
          unit_price: '1299.00',
          quantity: 1,
          item_list_id: 'new_in',
          item_list_name: 'New in',
        },
      ],
    },
    { locale: 'en' },
  );

  expect(event.transaction_id).toBe('ORD-1357');
  expect(event.value).toBe(1299);
  expect(event.items[0].item_list_id).toBe('new_in');
});

it('never emits NaN for a missing number', () => {
  // A NaN in a dataLayer value is dropped by GA4 without complaint, which is
  // how revenue quietly goes missing.
  const event = purchase({ order_number: 'ORD-1', items: [] }, { locale: 'en' });

  expect(event.value).toBe(0);
  expect(Number.isNaN(event.value)).toBe(false);
});
