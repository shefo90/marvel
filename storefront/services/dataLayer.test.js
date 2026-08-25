import { afterEach, beforeEach, expect, it } from 'vitest';

import { consentAndGtmSnippet, pushEvent } from './dataLayer.js';

beforeEach(() => {
  window.dataLayer = [];
});
afterEach(() => {
  delete window.dataLayer;
});

it('clears the previous ecommerce object before every push', () => {
  // GA4 merges successive pushes, so without the null the items from one event
  // are still attached to the next. It is the most common ecommerce tagging
  // defect and it is invisible in the interface.
  pushEvent({ event: 'view_item', locale: 'en', value: 100, items: [{ item_id: 'A' }] });

  expect(window.dataLayer[0]).toEqual({ ecommerce: null });
  expect(window.dataLayer[1].event).toBe('view_item');
});

it('nests the ecommerce payload and keeps event and locale outside it', () => {
  pushEvent({ event: 'add_to_cart', locale: 'ar', currency: 'EGP', value: 500, items: [] });

  const pushed = window.dataLayer[1];
  expect(pushed.locale).toBe('ar');
  expect(pushed.ecommerce).toEqual({ currency: 'EGP', value: 500, items: [] });
  expect(pushed.ecommerce.event).toBeUndefined();
});

it('denies every consent signal until the shopper says otherwise', () => {
  const snippet = consentAndGtmSnippet('GTM-TEST');

  expect(snippet).toContain("ad_storage:'denied'");
  expect(snippet).toContain("analytics_storage:'denied'");
  // The two Consent Mode v2 added. Omitting them makes Ads treat the whole
  // signal as missing rather than as denied.
  expect(snippet).toContain("ad_user_data:'denied'");
  expect(snippet).toContain("ad_personalization:'denied'");
});

it('sets the defaults before the container loads', () => {
  // Consent defaults set after GTM has loaded are set after tags have already
  // decided what to do, which is the failure Consent Mode exists to prevent.
  const snippet = consentAndGtmSnippet('GTM-TEST');

  expect(snippet.indexOf('consent')).toBeLessThan(snippet.indexOf('googletagmanager'));
});

it('still sets the defaults when no container is configured', () => {
  // So a container added later by any route starts from denied rather than
  // from nothing at all.
  const snippet = consentAndGtmSnippet(undefined);

  expect(snippet).toContain("ad_storage:'denied'");
  expect(snippet).not.toContain('googletagmanager');
});
