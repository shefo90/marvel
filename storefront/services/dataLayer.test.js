import { afterEach, beforeEach, expect, it } from 'vitest';

import { consentAndGtmSnippet, pushEvent, readConsentCookie, recordConsent } from './dataLayer.js';

beforeEach(() => {
  window.dataLayer = [];
  // The same shim the head snippet installs: gtag is just a dataLayer push.
  window.gtag = function gtag() {
    window.dataLayer.push(arguments);
  };
});
afterEach(() => {
  delete window.dataLayer;
  delete window.gtag;
  document.cookie = 'consent=; path=/; max-age=0';
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

it('opens the defaults to granted when the shopper has already accepted', () => {
  // A returning visitor who accepted should have analytics from the very first
  // hit of the session, not after the banner re-fires an update.
  const snippet = consentAndGtmSnippet('GTM-TEST', 'granted');

  expect(snippet).toContain("ad_storage:'granted'");
  expect(snippet).toContain("ad_user_data:'granted'");
  expect(snippet).toContain("ad_personalization:'granted'");
  expect(snippet).toContain("analytics_storage:'granted'");
  // Redaction is a denied-state measure; with storage granted it is contradictory.
  expect(snippet).not.toContain('ads_data_redaction');
});

it('keeps denying when the stored choice is a refusal', () => {
  const snippet = consentAndGtmSnippet('GTM-TEST', 'denied');

  expect(snippet).toContain("analytics_storage:'denied'");
  expect(snippet).toContain('ads_data_redaction');
});

it('reads the consent choice out of a Cookie header', () => {
  expect(readConsentCookie('foo=bar; consent=granted; baz=1')).toBe('granted');
  expect(readConsentCookie('consent=denied')).toBe('denied');
});

it('treats a missing or unrecognised consent cookie as no choice yet', () => {
  expect(readConsentCookie('foo=bar')).toBeNull();
  expect(readConsentCookie(undefined)).toBeNull();
  expect(readConsentCookie('consent=maybe')).toBeNull();
});

it('records an acceptance as both a cookie and a consent update', () => {
  recordConsent('granted');

  expect(document.cookie).toContain('consent=granted');
  expect(Array.from(window.dataLayer.at(-1))).toEqual([
    'consent',
    'update',
    {
      ad_storage: 'granted',
      ad_user_data: 'granted',
      ad_personalization: 'granted',
      analytics_storage: 'granted',
    },
  ]);
});

it('records a refusal without granting anything', () => {
  recordConsent('denied');

  expect(document.cookie).toContain('consent=denied');
  expect(Array.from(window.dataLayer.at(-1))).toEqual([
    'consent',
    'update',
    {
      ad_storage: 'denied',
      ad_user_data: 'denied',
      ad_personalization: 'denied',
      analytics_storage: 'denied',
    },
  ]);
});
