import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import * as account from '../services/account.service.js';
import { useLocale } from './useLocale.jsx';

/**
 * Who is signed in, client-side only.
 *
 * Never part of the server render, for the same reason the cart is not: this is
 * one person's identity, and a server-rendered copy is a page a cache can hand
 * to somebody else.
 *
 * **The session is resumed on mount, and that is not optional.** The access
 * token lives in memory, so pressing F5 loses it. What survives is the httpOnly
 * refresh cookie, so the provider spends one request asking whether a session
 * sits behind that cookie before deciding anybody is anonymous. Without it,
 * every reload signs the shopper out and the cookie's whole purpose is wasted.
 *
 * A failed resume is not an error. Arriving signed out is the ordinary state of
 * a shop; only a deliberate sign-in that fails has something to tell anyone.
 */
const AccountContext = createContext(null);

export function AccountProvider({ children }) {
  const { locale } = useLocale();
  const [shopper, setShopper] = useState(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    account
      .refreshSession(locale)
      .then(() => account.getProfile(locale))
      .then((profile) => {
        if (!cancelled) setShopper(profile);
      })
      .catch(() => {
        /* no session behind the cookie: an anonymous visitor, not a failure */
      })
      .finally(() => {
        if (!cancelled) setReady(true);
      });

    return () => {
      cancelled = true;
    };
  }, [locale]);

  const messageFrom = (failure) =>
    failure?.response?.data?.detail ?? 'Something went wrong. Please try again.';

  const signIn = useCallback(
    async (credentials) => {
      setBusy(true);
      setError(null);
      try {
        await account.signIn(locale, credentials);
        setShopper(await account.getProfile(locale));
        return true;
      } catch (failure) {
        setError(messageFrom(failure));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [locale],
  );

  const register = useCallback(
    async (payload) => {
      setBusy(true);
      setError(null);
      try {
        await account.register(locale, payload);
        // Registration does not issue tokens -- the API keeps account creation
        // and session creation apart so there is one path that mints them -- so
        // the new shopper is signed in here rather than being asked to type the
        // password they just chose a second time.
        await account.signIn(locale, { email: payload.email, password: payload.password });
        setShopper(await account.getProfile(locale));
        return true;
      } catch (failure) {
        setError(messageFrom(failure));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [locale],
  );

  const signOut = useCallback(async () => {
    setBusy(true);
    try {
      await account.signOut(locale);
    } finally {
      // Cleared whatever the server said. A sign-out that leaves the shopper
      // looking signed in because the network blipped is the one failure they
      // would never think to check.
      setShopper(null);
      setBusy(false);
    }
  }, [locale]);

  const clearError = useCallback(() => setError(null), []);

  const value = useMemo(
    () => ({ shopper, ready, busy, error, signIn, signOut, register, clearError }),
    [shopper, ready, busy, error, signIn, signOut, register, clearError],
  );

  return <AccountContext.Provider value={value}>{children}</AccountContext.Provider>;
}

export function useAccount() {
  const value = useContext(AccountContext);
  if (value === null) {
    throw new Error('useAccount must be used inside an AccountProvider');
  }
  return value;
}
