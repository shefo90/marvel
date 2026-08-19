import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';

import { api, normalizeError, setAuthHandlers, setAuthTokens } from './api.js';

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  setAuthTokens(null);
  setAuthHandlers({});
});
afterAll(() => server.close());

describe('normalizeError', () => {
  it('reads a plain string detail', () => {
    const error = normalizeError({
      response: { status: 409, data: { detail: 'slug already in use' } },
    });

    expect(error.status).toBe(409);
    expect(error.message).toBe('slug already in use');
  });

  it('keeps a publish blocker list as blockers', () => {
    const detail = [
      { code: 'no_variant', message: 'Add at least one variant before publishing.' },
    ];

    const error = normalizeError({ response: { status: 422, data: { detail } } });

    expect(error.blockers).toEqual(detail);
  });

  it('maps a pydantic validation list onto field names', () => {
    // Same status, same container type, completely different shape. A UI that
    // assumes one of the three renders "[object Object]" for the other two.
    const detail = [
      { loc: ['body', 'item_group_id'], msg: 'String should have at most 64 characters', type: 'string_too_long' },
    ];

    const error = normalizeError({ response: { status: 422, data: { detail } } });

    expect(error.fieldErrors.item_group_id).toBe('String should have at most 64 characters');
    expect(error.blockers).toEqual([]);
  });

  it('survives a response with no body at all', () => {
    const error = normalizeError({ message: 'Network Error' });

    expect(error.status).toBe(0);
    expect(error.message).toBeTruthy();
  });
});

describe('the 401 interceptor', () => {
  it('refreshes once and retries the original request', async () => {
    let attempts = 0;
    server.use(
      http.get('*/api/admin/products', ({ request }) => {
        attempts += 1;
        const auth = request.headers.get('authorization');
        if (auth === 'Bearer fresh') return HttpResponse.json({ items: [] });
        return new HttpResponse(null, { status: 401 });
      }),
      http.post('*/api/en/auth/staff/refresh', () =>
        HttpResponse.json({
          access_token: 'fresh',
          refresh_token: 'fresh-refresh',
          token_type: 'bearer',
          expires_in: 1800,
          scope: 'staff',
        }),
      ),
    );
    setAuthTokens({ accessToken: 'stale', refreshToken: 'valid-refresh' });

    const response = await api.get('/admin/products');

    expect(response.data).toEqual({ items: [] });
    expect(attempts).toBe(2);
  });

  it('fires exactly one refresh for concurrent 401s', async () => {
    // Rotation revokes the token it was given, so a second concurrent refresh
    // presents a token that has just been revoked and fails by design. One
    // in-flight promise shared by every waiter is the only correct shape.
    let refreshes = 0;
    server.use(
      http.get('*/api/admin/products', ({ request }) =>
        request.headers.get('authorization') === 'Bearer fresh'
          ? HttpResponse.json({ items: [] })
          : new HttpResponse(null, { status: 401 }),
      ),
      http.post('*/api/en/auth/staff/refresh', () => {
        refreshes += 1;
        return HttpResponse.json({
          access_token: 'fresh',
          refresh_token: 'fresh-refresh',
          token_type: 'bearer',
          expires_in: 1800,
          scope: 'staff',
        });
      }),
    );
    setAuthTokens({ accessToken: 'stale', refreshToken: 'valid-refresh' });

    await Promise.all([
      api.get('/admin/products'),
      api.get('/admin/products'),
      api.get('/admin/products'),
    ]);

    expect(refreshes).toBe(1);
  });

  it('signs the operator out when the refresh itself fails', async () => {
    const onFailure = vi.fn();
    server.use(
      http.get('*/api/admin/products', () => new HttpResponse(null, { status: 401 })),
      http.post('*/api/en/auth/staff/refresh', () => new HttpResponse(null, { status: 401 })),
    );
    setAuthTokens({ accessToken: 'stale', refreshToken: 'dead-refresh' });
    setAuthHandlers({ onFailure });

    await expect(api.get('/admin/products')).rejects.toMatchObject({ status: 401 });
    expect(onFailure).toHaveBeenCalledTimes(1);
  });

  it('does not try to refresh when there is no refresh token', async () => {
    // The login request itself 401s on bad credentials. Treating that as an
    // expired session would fire a refresh with no token and report the wrong
    // error to someone who simply mistyped their password.
    let refreshes = 0;
    server.use(
      http.post('*/api/en/auth/staff/login', () => new HttpResponse(null, { status: 401 })),
      http.post('*/api/en/auth/staff/refresh', () => {
        refreshes += 1;
        return new HttpResponse(null, { status: 401 });
      }),
    );

    await expect(api.post('/en/auth/staff/login', {})).rejects.toMatchObject({ status: 401 });
    expect(refreshes).toBe(0);
  });
});
