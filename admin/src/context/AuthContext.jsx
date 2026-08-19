import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { setAuthHandlers, setAuthTokens } from '../services/api.js';
import { decodeClaims } from '../utils/jwt.js';

/**
 * The session, held in memory and nowhere else.
 *
 * Not localStorage, not sessionStorage, not a cookie this script can read. The
 * admin shares an origin with a storefront that loads GTM, GA4 and Meta Pixel,
 * any of which can change without us acting; a refresh token reachable from
 * JavaScript there is a fourteen-day admin credential. The cost is that
 * reloading the tab means logging in again, which is the deal we took.
 *
 * `user` is decoded from the access token for display only — hiding the COGS
 * field below `admin`. The API re-reads the actor from the database on every
 * request and answers 403 regardless of what this decided to render.
 */
const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [session, setSession] = useState(null);

  const signIn = useCallback((pair) => {
    setSession({
      accessToken: pair.access_token,
      refreshToken: pair.refresh_token,
      user: decodeClaims(pair.access_token),
    });
  }, []);

  const signOut = useCallback(() => setSession(null), []);

  // services/api.js is not a React module and cannot read this state. Without
  // this push it holds no token at all and every request goes out
  // unauthenticated — which fails as a 403, not as an obvious wiring error.
  useEffect(() => {
    setAuthTokens(
      session === null
        ? null
        : { accessToken: session.accessToken, refreshToken: session.refreshToken },
    );
  }, [session]);

  // The interceptor rotates tokens on its own. Feeding the new pair back here
  // keeps React's copy from being stale — otherwise the effect above would
  // eventually push the pre-rotation tokens back over the live ones, and the
  // old refresh token is already revoked.
  useEffect(() => {
    setAuthHandlers({
      onRefreshed: (pair) =>
        setSession((current) =>
          current === null
            ? null
            : {
                accessToken: pair.access_token,
                refreshToken: pair.refresh_token,
                user: decodeClaims(pair.access_token),
              },
        ),
      onFailure: () => setSession(null),
    });
    return () => setAuthHandlers({});
  }, []);

  const value = useMemo(
    () => ({ session, signIn, signOut }),
    [session, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuthContext() {
  const value = useContext(AuthContext);
  if (value === null) {
    throw new Error('useAuthContext must be used inside an AuthProvider');
  }
  return value;
}
