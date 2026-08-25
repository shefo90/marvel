import axios from 'axios';

/**
 * One API client that works on both sides of the render.
 *
 * On the server there is no origin to be relative to, so it needs an absolute
 * one; in the browser the call must stay same-origin or it becomes a CORS
 * problem the API has no middleware for. Getting this backwards is the classic
 * SSR failure: the page renders on the server and every hydrated interaction
 * 404s, or vice versa.
 */
const isServer = typeof window === 'undefined';

const SERVER_ORIGIN =
  (isServer && (process.env.API_ORIGIN || 'http://localhost:8000')) || '';

export const api = axios.create({
  baseURL: isServer ? `${SERVER_ORIGIN}/api` : '/api',
  // A slow API must not hold a server render open indefinitely; a timed-out
  // page is recoverable, a hung worker is not.
  timeout: isServer ? 8000 : 15000,
});

export function publicOrigin() {
  if (isServer) return (process.env.PUBLIC_ORIGIN || 'http://localhost:3000').replace(/\/$/, '');
  return window.location.origin;
}

/** The shopper's cart token. Not a credential — it identifies a basket. */
const CART_TOKEN_KEY = 'marvel.cart.token';

export function readCartToken() {
  if (isServer) return null;
  try {
    return window.localStorage.getItem(CART_TOKEN_KEY);
  } catch {
    // Private browsing, or storage disabled. A shopper without a stored token
    // simply gets a new cart rather than an error.
    return null;
  }
}

export function writeCartToken(token) {
  if (isServer) return;
  try {
    window.localStorage.setItem(CART_TOKEN_KEY, token);
  } catch {
    /* nothing to do: the cart lives for this page view only */
  }
}

export function clearCartToken() {
  if (isServer) return;
  try {
    window.localStorage.removeItem(CART_TOKEN_KEY);
  } catch {
    /* see above */
  }
}
