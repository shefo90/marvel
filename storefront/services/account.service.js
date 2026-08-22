import axios from 'axios';

import { api } from './api.js';

/**
 * The signed-in shopper: session, orders, addresses.
 *
 * **The access token lives in this module and nowhere else.** Not
 * `localStorage`, not `sessionStorage`, not a cookie the page can read. The
 * refresh token is in an httpOnly cookie the browser attaches for us and
 * JavaScript cannot see, so an XSS on the storefront can act while the tab is
 * open but cannot carry a credential away from it. Writing the access token to
 * storage would hand most of that back — see backend/services/session_cookies.py
 * for the whole argument.
 *
 * **A separate axios instance from `api`.** The bearer header and the refresh
 * interceptor belong on account calls only. Attaching them to catalog reads
 * would make requests that are identical for every shopper vary by header, and
 * a varying request is one a cache cannot share.
 *
 * Client-side only. There is no server render of any of this: an account page
 * holds one person's orders, and a server-rendered one is a page a cache can
 * hand to somebody else.
 */

const accountApi = axios.create({
  baseURL: api.defaults.baseURL,
  timeout: api.defaults.timeout,
});

let token = null;
let refreshInFlight = null;

export function accessToken() {
  return token;
}

/** Test seam. Production code has no reason to drop the session silently. */
export function __resetSession() {
  token = null;
  refreshInFlight = null;
}

/**
 * The CSRF value, read from the cookie the server set.
 *
 * Readable on purpose: double-submit works because another origin cannot read
 * our cookies, not because this one cannot. Returns null rather than throwing
 * when cookies are unavailable, so a blocked-cookie browser fails at the
 * request with a server error rather than here with a stack trace.
 */
function csrfToken() {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(/(?:^|;\s*)marvel_csrf=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : null;
}

function withCsrf(headers = {}) {
  const csrf = csrfToken();
  return csrf ? { ...headers, 'X-CSRF-Token': csrf } : headers;
}

accountApi.interceptors.request.use((config) => {
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

/** `/en/account/orders` -> `en`. The locale is a path segment, never a header. */
function localeOf(url = '') {
  const match = url.match(/^\/?([a-z]{2})\//);
  return match ? match[1] : 'en';
}

/**
 * One rotation at a time, shared by every waiter.
 *
 * Rotation revokes the token it was handed, so two concurrent refreshes mean
 * the second presents a token that was just revoked — it fails, and the shopper
 * is signed out mid-page for no reason. Two requests failing together on one
 * page load is the normal case, not the rare one.
 *
 * Bare `axios`, not `accountApi`, so a failing refresh cannot recurse back into
 * the interceptor that calls it.
 */
function rotate(locale) {
  if (refreshInFlight === null) {
    refreshInFlight = axios
      .post(`${api.defaults.baseURL}/${locale}/account/session/refresh`, null, {
        headers: withCsrf(),
        withCredentials: true,
      })
      .then((response) => {
        token = response.data.access_token;
        return response.data;
      })
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

accountApi.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error?.config;
    const status = error?.response?.status;

    // A 401 from the session endpoints is not an expired session: it is a wrong
    // password, or a refresh with no cookie behind it. Retrying either would
    // report a expired session to someone who simply mistyped, and would
    // recurse on the refresh path.
    const isSessionCall = original?.url?.includes('/account/session');
    const canRetry = status === 401 && original && !original._retried && !isSessionCall;

    if (!canRetry) return Promise.reject(error);

    original._retried = true;
    try {
      await rotate(localeOf(original.url));
      return await accountApi(original);
    } catch (refreshFailure) {
      // The session is genuinely gone. Dropping the token here means the next
      // render sees a signed-out shopper rather than retrying forever.
      token = null;
      return Promise.reject(refreshFailure);
    }
  },
);

// --- session -------------------------------------------------------------

export async function signIn(locale, { email, password }) {
  const response = await accountApi.post(
    `/${locale}/account/session`,
    { email, password },
    { withCredentials: true },
  );
  token = response.data.access_token;
  return response.data;
}

export async function register(locale, payload) {
  // Registration deliberately does not sign anyone in: the API keeps account
  // creation and session creation separate so there is exactly one code path
  // that issues shopper tokens. The caller signs in next.
  const response = await accountApi.post(`/${locale}/auth/register`, payload);
  return response.data;
}

export async function refreshSession(locale) {
  return rotate(locale);
}

export async function signOut(locale) {
  try {
    await accountApi.delete(`/${locale}/account/session`, {
      headers: withCsrf(),
      withCredentials: true,
    });
  } finally {
    // Forgotten locally whatever the server said. A sign-out that leaves the
    // token in memory because the network blipped is the one failure a shopper
    // would never think to check.
    token = null;
  }
}

// --- reads ---------------------------------------------------------------

export async function getProfile(locale) {
  const response = await accountApi.get(`/${locale}/account/me`);
  return response.data;
}

export async function getOrders(locale) {
  const response = await accountApi.get(`/${locale}/account/orders`);
  return response.data;
}

export async function getOrder(locale, orderNumber) {
  const response = await accountApi.get(`/${locale}/account/orders/${orderNumber}`);
  return response.data;
}

// --- addresses -----------------------------------------------------------

export async function listAddresses(locale) {
  const response = await accountApi.get(`/${locale}/account/addresses`);
  return response.data;
}

export async function createAddress(locale, payload) {
  const response = await accountApi.post(`/${locale}/account/addresses`, payload);
  return response.data;
}

export async function updateAddress(locale, addressId, payload) {
  const response = await accountApi.patch(
    `/${locale}/account/addresses/${addressId}`,
    payload,
  );
  return response.data;
}

export async function archiveAddress(locale, addressId) {
  await accountApi.delete(`/${locale}/account/addresses/${addressId}`);
}
