import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';

import { api } from './api.js';
import {
  __resetSession,
  accessToken,
  getOrders,
  listAddresses,
  refreshSession,
  signIn,
  signOut,
} from './account.service.js';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  __resetSession();
  document.cookie = 'marvel_csrf=; max-age=0; path=/';
});
afterAll(() => server.close());

beforeEach(() => {
  // The CSRF cookie is readable by design — the page has to echo it — so the
  // browser half of double-submit is simulated by setting it here.
  document.cookie = 'marvel_csrf=csrf-value; path=/';
});

function serveSignIn(token = 'access-1') {
  server.use(
    http.post('*/api/en/account/session', () =>
      HttpResponse.json({ access_token: token, token_type: 'bearer', csrf_token: 'csrf-value' }),
    ),
  );
}

describe('the access token', () => {
  it('is held in memory after signing in', async () => {
    serveSignIn();

    await signIn('en', { email: 'nour@example.com', password: 'x' });

    expect(accessToken()).toBe('access-1');
  });

  it('never reaches localStorage', async () => {
    // The entire reason the refresh token is in an httpOnly cookie. Writing the
    // access token to storage would hand back most of what that buys.
    serveSignIn();

    await signIn('en', { email: 'nour@example.com', password: 'x' });

    const stored = Object.keys(window.localStorage);
    expect(stored.some((key) => window.localStorage.getItem(key)?.includes('access-1'))).toBe(
      false,
    );
  });

  it('is sent as a bearer header on account requests', async () => {
    serveSignIn();
    let seen = null;
    server.use(
      http.get('*/api/en/account/orders', ({ request }) => {
        seen = request.headers.get('authorization');
        return HttpResponse.json([]);
      }),
    );
    await signIn('en', { email: 'nour@example.com', password: 'x' });

    await getOrders('en');

    expect(seen).toBe('Bearer access-1');
  });

  it('is forgotten on sign out', async () => {
    serveSignIn();
    server.use(http.delete('*/api/en/account/session', () => new HttpResponse(null, { status: 204 })));
    await signIn('en', { email: 'nour@example.com', password: 'x' });

    await signOut('en');

    expect(accessToken()).toBeNull();
  });
});

describe('CSRF', () => {
  it('echoes the readable cookie on refresh', async () => {
    let seen = null;
    server.use(
      http.post('*/api/en/account/session/refresh', ({ request }) => {
        seen = request.headers.get('x-csrf-token');
        return HttpResponse.json({ access_token: 'access-2', csrf_token: 'csrf-value' });
      }),
    );

    await refreshSession('en');

    expect(seen).toBe('csrf-value');
  });

  it('echoes it on sign out too, which is also a cookie-authenticated write', async () => {
    let seen = null;
    server.use(
      http.delete('*/api/en/account/session', ({ request }) => {
        seen = request.headers.get('x-csrf-token');
        return new HttpResponse(null, { status: 204 });
      }),
    );

    await signOut('en');

    expect(seen).toBe('csrf-value');
  });
});

describe('silent refresh', () => {
  it('retries the original request once after a 401', async () => {
    let calls = 0;
    server.use(
      http.get('*/api/en/account/orders', ({ request }) => {
        calls += 1;
        if (request.headers.get('authorization') !== 'Bearer access-2') {
          return new HttpResponse(null, { status: 401 });
        }
        return HttpResponse.json([{ order_number: 'MRV-1' }]);
      }),
      http.post('*/api/en/account/session/refresh', () =>
        HttpResponse.json({ access_token: 'access-2', csrf_token: 'csrf-value' }),
      ),
    );

    const orders = await getOrders('en');

    expect(orders).toEqual([{ order_number: 'MRV-1' }]);
    expect(calls).toBe(2);
  });

  it('rotates only once when several requests fail together', async () => {
    // Rotation revokes the token it was handed. Two concurrent refreshes mean
    // the second presents a token that was just revoked, and the shopper is
    // signed out mid-page for no reason.
    let refreshes = 0;
    server.use(
      http.get('*/api/en/account/orders', ({ request }) =>
        request.headers.get('authorization') === 'Bearer access-2'
          ? HttpResponse.json([])
          : new HttpResponse(null, { status: 401 }),
      ),
      http.get('*/api/en/account/addresses', ({ request }) =>
        request.headers.get('authorization') === 'Bearer access-2'
          ? HttpResponse.json([])
          : new HttpResponse(null, { status: 401 }),
      ),
      http.post('*/api/en/account/session/refresh', () => {
        refreshes += 1;
        return HttpResponse.json({ access_token: 'access-2', csrf_token: 'csrf-value' });
      }),
    );

    await Promise.all([getOrders('en'), listAddresses('en')]);

    expect(refreshes).toBe(1);
  });

  it('gives up rather than looping when the refresh itself fails', async () => {
    let refreshes = 0;
    server.use(
      http.get('*/api/en/account/orders', () => new HttpResponse(null, { status: 401 })),
      http.post('*/api/en/account/session/refresh', () => {
        refreshes += 1;
        return new HttpResponse(null, { status: 401 });
      }),
    );

    await expect(getOrders('en')).rejects.toBeTruthy();
    expect(refreshes).toBe(1);
    expect(accessToken()).toBeNull();
  });

  it('does not try to refresh a failed sign-in', async () => {
    // A 401 from the login endpoint is a mistyped password, not an expired
    // session. Refreshing there reports the wrong thing to the shopper.
    let refreshes = 0;
    server.use(
      http.post('*/api/en/account/session', () => new HttpResponse(null, { status: 401 })),
      http.post('*/api/en/account/session/refresh', () => {
        refreshes += 1;
        return HttpResponse.json({ access_token: 'x', csrf_token: 'csrf-value' });
      }),
    );

    await expect(signIn('en', { email: 'nour@example.com', password: 'wrong' })).rejects.toBeTruthy();
    expect(refreshes).toBe(0);
  });
});

describe('the cart client is untouched', () => {
  it('leaves plain catalog requests unauthenticated', async () => {
    // The bearer header belongs on account calls. Attaching it to catalog reads
    // would make them uncacheable for no benefit.
    serveSignIn();
    let seen = 'unset';
    server.use(
      http.get('*/api/en/products', ({ request }) => {
        seen = request.headers.get('authorization');
        return HttpResponse.json({ items: [] });
      }),
    );
    await signIn('en', { email: 'nour@example.com', password: 'x' });

    await api.get('/en/products');

    expect(seen).toBeNull();
  });
});
