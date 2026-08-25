import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';

import { api } from '../services/api.js';
import { AuthProvider, useAuthContext } from './AuthContext.jsx';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// A staff access token: header.payload.signature, payload readable, signature
// irrelevant here because nothing in the browser verifies it.
function fakeToken(claims) {
  const encode = (value) => btoa(JSON.stringify(value)).replace(/=+$/, '');
  return `${encode({ alg: 'HS256' })}.${encode(claims)}.signature`;
}

function Harness() {
  const { session, signIn, signOut } = useAuthContext();
  return (
    <div>
      <span data-testid="role">{session?.user?.role ?? 'anonymous'}</span>
      <button
        type="button"
        onClick={() =>
          signIn({
            access_token: fakeToken({ sub: 'ops@example.com', role: 'catalog', access_level: 2 }),
            refresh_token: 'refresh-1',
            expires_in: 1800,
          })
        }
      >
        sign in
      </button>
      <button type="button" onClick={signOut}>
        sign out
      </button>
      {/*
        Swallowed here, not at the call site in the test. One of these tests
        answers a 403 on purpose, and an unhandled rejection escaping the click
        handler makes Vitest report an error for a run whose assertions all
        passed -- which it warns may be hiding false positives elsewhere.
      */}
      <button type="button" onClick={() => { api.get('/admin/products').catch(() => {}); }}>
        fetch
      </button>
    </div>
  );
}

it('makes the signed-in token available to the API layer', async () => {
  // The context holding a token that services/api.js never learns about is a
  // silent failure: every request goes out unauthenticated and comes back 403.
  let seen = null;
  server.use(
    http.get('*/api/admin/products', ({ request }) => {
      seen = request.headers.get('authorization');
      return HttpResponse.json({ items: [] });
    }),
  );
  const user = userEvent.setup();
  render(
    <AuthProvider>
      <Harness />
    </AuthProvider>,
  );

  await user.click(screen.getByRole('button', { name: 'sign in' }));
  await user.click(screen.getByRole('button', { name: 'fetch' }));

  expect(seen).toMatch(/^Bearer /);
});

it('reads the role out of the access token for display', async () => {
  const user = userEvent.setup();
  render(
    <AuthProvider>
      <Harness />
    </AuthProvider>,
  );
  expect(screen.getByTestId('role')).toHaveTextContent('anonymous');

  await user.click(screen.getByRole('button', { name: 'sign in' }));

  expect(screen.getByTestId('role')).toHaveTextContent('catalog');
});

it('stops sending the token after signing out', async () => {
  let seen = 'not called';
  server.use(
    http.get('*/api/admin/products', ({ request }) => {
      seen = request.headers.get('authorization');
      return new HttpResponse(null, { status: 403 });
    }),
  );
  const user = userEvent.setup();
  render(
    <AuthProvider>
      <Harness />
    </AuthProvider>,
  );

  await user.click(screen.getByRole('button', { name: 'sign in' }));
  await user.click(screen.getByRole('button', { name: 'sign out' }));
  await user.click(screen.getByRole('button', { name: 'fetch' })).catch(() => {});

  expect(seen).toBeNull();
});
