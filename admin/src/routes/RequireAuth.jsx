import { Navigate, useLocation } from 'react-router-dom';

import { useAuthContext } from '../context/AuthContext.jsx';

/**
 * Gate for everything that is not the login screen.
 *
 * The redirect happens before the child renders rather than after a failed
 * request, so nobody sees admin chrome they are not entitled to — and no
 * protected page fires a query that is guaranteed to 401.
 *
 * `state.from` is carried so a session that expires mid-task returns the
 * operator to where they were instead of to the listing.
 */
export default function RequireAuth({ children }) {
  const { session } = useAuthContext();
  const location = useLocation();

  if (session === null) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return children;
}
