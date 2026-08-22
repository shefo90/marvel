import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, beforeEach, expect, it } from 'vitest';

import { renderAt } from '../test/render.jsx';
import { __resetSession } from '../services/account.service.js';
import { AccountProvider, useAccount } from './useAccount.jsx';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  __resetSession();
});
afterAll(() => server.close());

beforeEach(() => {
  document.cookie = 'marvel_csrf=csrf-value; path=/';
});

function Harness() {
  const { shopper, ready, signIn, signOut, error } = useAccount();
  return (
    <div>
      <span data-testid="who">{shopper ? shopper.email : 'anonymous'}</span>
      <span data-testid="ready">{ready ? 'ready' : 'loading'}</span>
      <span data-testid="error">{error ?? ''}</span>
      <button type="button" onClick={() => signIn({ email: 'nour@example.com', password: 'x' })}>
        sign in
      </button>
      <button type="button" onClick={() => signOut()}>
        sign out
      </button>
    </div>
  );
}

function renderHarness() {
  return renderAt(
    <AccountProvider>
      <Harness />
    </AccountProvider>,
  );
}

/** A shopper whose refresh cookie is still good. */
function serveReturningVisitor() {
  server.use(
    http.post('*/api/en/account/session/refresh', () =>
      HttpResponse.json({ access_token: 'access-1', csrf_token: 'csrf-value' }),
    ),
    http.get('*/api/en/account/me', () =>
      HttpResponse.json({ email: 'nour@example.com', orders_count: 2 }),
    ),
  );
}

/** Nobody signed in: the refresh cookie is absent or spent. */
function serveAnonymous() {
  server.use(
    http.post('*/api/en/account/session/refresh', () => new HttpResponse(null, { status: 401 })),
  );
}

it('reports anonymous when there is no session to resume', async () => {
  serveAnonymous();
  renderHarness();

  await waitFor(() => expect(screen.getByTestId('ready')).toHaveTextContent('ready'));
  expect(screen.getByTestId('who')).toHaveTextContent('anonymous');
});

it('resumes a session from the cookie on first load', async () => {
  // The access token is in memory, so a page refresh loses it. The httpOnly
  // cookie is what survives, and trying it once on mount is the only thing
  // standing between a signed-in shopper and being logged out by F5.
  serveReturningVisitor();
  renderHarness();

  await waitFor(() => expect(screen.getByTestId('who')).toHaveTextContent('nour@example.com'));
});

it('does not report an expired cookie as an error', async () => {
  // Arriving signed out is the normal state of a shop, not a failure.
  serveAnonymous();
  renderHarness();

  await waitFor(() => expect(screen.getByTestId('ready')).toHaveTextContent('ready'));
  expect(screen.getByTestId('error')).toHaveTextContent('');
});

it('signs a shopper in', async () => {
  serveAnonymous();
  server.use(
    http.post('*/api/en/account/session', () =>
      HttpResponse.json({ access_token: 'access-1', csrf_token: 'csrf-value' }),
    ),
    http.get('*/api/en/account/me', () =>
      HttpResponse.json({ email: 'nour@example.com', orders_count: 0 }),
    ),
  );
  const user = userEvent.setup();
  renderHarness();
  await waitFor(() => expect(screen.getByTestId('ready')).toHaveTextContent('ready'));

  await user.click(screen.getByRole('button', { name: 'sign in' }));

  await waitFor(() => expect(screen.getByTestId('who')).toHaveTextContent('nour@example.com'));
});

it('shows the reason a sign-in was refused', async () => {
  serveAnonymous();
  server.use(
    http.post('*/api/en/account/session', () =>
      HttpResponse.json({ detail: 'invalid email or password' }, { status: 401 }),
    ),
  );
  const user = userEvent.setup();
  renderHarness();
  await waitFor(() => expect(screen.getByTestId('ready')).toHaveTextContent('ready'));

  await user.click(screen.getByRole('button', { name: 'sign in' }));

  await waitFor(() =>
    expect(screen.getByTestId('error')).toHaveTextContent('invalid email or password'),
  );
});

it('signs a shopper out', async () => {
  serveReturningVisitor();
  server.use(
    http.delete('*/api/en/account/session', () => new HttpResponse(null, { status: 204 })),
  );
  const user = userEvent.setup();
  renderHarness();
  await waitFor(() => expect(screen.getByTestId('who')).toHaveTextContent('nour@example.com'));

  await user.click(screen.getByRole('button', { name: 'sign out' }));

  await waitFor(() => expect(screen.getByTestId('who')).toHaveTextContent('anonymous'));
});
