import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import * as cartService from '../services/cart.service.js';
import { useLocale } from './useLocale.jsx';

/**
 * The basket, client-side only.
 *
 * Never part of the server render: it is per-shopper state with nothing to
 * index, and rendering it on the server would mean a cache could hold one
 * shopper's basket and hand it to another.
 */
const CartContext = createContext(null);

export function CartProvider({ children }) {
  const { locale } = useLocale();
  const [cart, setCart] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  // Loaded after hydration, deliberately. Nothing here belongs in the HTML.
  useEffect(() => {
    let cancelled = false;
    cartService
      .ensureCart(locale)
      .then((next) => {
        if (!cancelled) setCart(next);
      })
      .catch(() => {
        /* a missing cart is not an error to show anyone */
      });
    return () => {
      cancelled = true;
    };
  }, [locale]);

  const run = useCallback(async (operation) => {
    setBusy(true);
    setError(null);
    try {
      setCart(await operation());
    } catch (failure) {
      setError(failure?.response?.data?.detail ?? 'Something went wrong.');
    } finally {
      setBusy(false);
    }
  }, []);

  const value = useMemo(
    () => ({
      cart,
      busy,
      error,
      itemCount: cart?.item_count ?? 0,
      add: (input) => run(() => cartService.addItem(locale, input)),
      setQuantity: (variantId, quantity) =>
        run(() => cartService.setQuantity(locale, variantId, quantity)),
      remove: (variantId) => run(() => cartService.removeItem(locale, variantId)),
      refresh: () => run(() => cartService.ensureCart(locale)),
      reset: () => setCart(null),
    }),
    [cart, busy, error, locale, run],
  );

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
}

export function useCart() {
  const value = useContext(CartContext);
  if (value === null) throw new Error('useCart must be used inside a CartProvider');
  return value;
}
