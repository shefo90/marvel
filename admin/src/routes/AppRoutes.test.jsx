import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, it } from 'vitest';

import { AuthProvider } from '../context/AuthContext.jsx';
import AppRoutes from './AppRoutes.jsx';

function renderAt(path) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it('sends an unauthenticated visitor to the login screen', () => {
  renderAt('/products');

  expect(screen.getByRole('heading', { name: /sign in/i })).toBeInTheDocument();
});

it('does not render a protected page to an unauthenticated visitor', () => {
  // The redirect has to happen before the page renders, not after: a products
  // table that mounts and fires its query would 401 on the way out anyway, but
  // it would also flash real chrome at someone who is not logged in.
  renderAt('/products');

  expect(screen.queryByRole('table')).not.toBeInTheDocument();
});
