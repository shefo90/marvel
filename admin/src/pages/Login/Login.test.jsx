import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter } from 'react-router-dom';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';

import { AuthProvider } from '../../context/AuthContext.jsx';
import AppRoutes from '../../routes/AppRoutes.jsx';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function encode(value) {
  return btoa(JSON.stringify(value)).replace(/=+$/, '');
}

const TOKEN = `${encode({ alg: 'HS256' })}.${encode({
  sub: 'ops@example.com',
  role: 'catalog',
  access_level: 2,
})}.sig`;

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/login']}>
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function submitCredentials(user) {
  await user.type(screen.getByLabelText(/email/i), 'ops@example.com');
  await user.type(screen.getByLabelText(/password/i), 'correct-horse');
  await user.click(screen.getByRole('button', { name: /sign in/i }));
}

it('lands on the product listing after a successful sign in', async () => {
  server.use(
    http.post('*/api/en/auth/staff/login', () =>
      HttpResponse.json({
        access_token: TOKEN,
        refresh_token: 'refresh-1',
        token_type: 'bearer',
        expires_in: 1800,
        scope: 'staff',
      }),
    ),
  );
  const user = userEvent.setup();
  renderApp();

  await submitCredentials(user);

  expect(await screen.findByRole('heading', { name: 'Products' })).toBeInTheDocument();
});

it('reports a rejected sign in without disclosing which half was wrong', async () => {
  server.use(
    http.post('*/api/en/auth/staff/login', () =>
      HttpResponse.json({ detail: 'invalid credentials' }, { status: 401 }),
    ),
  );
  const user = userEvent.setup();
  renderApp();

  await submitCredentials(user);

  expect(await screen.findByRole('alert')).toHaveTextContent(/invalid credentials/i);
  expect(screen.getByRole('heading', { name: /sign in/i })).toBeInTheDocument();
});
