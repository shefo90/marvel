import { api, clearCartToken, readCartToken, writeCartToken } from './api.js';

/**
 * The cart lives entirely in the browser's session with the API.
 *
 * Never server-rendered: it is per-shopper state with nothing to index, and
 * rendering it on the server would mean caching a basket — which is how one
 * shopper ends up seeing another's.
 */
function auth() {
  const token = readCartToken();
  return token ? { headers: { 'X-Cart-Token': token } } : {};
}

export async function ensureCart(locale) {
  const token = readCartToken();
  if (token) {
    try {
      const response = await api.get(`/${locale}/cart`, auth());
      return response.data;
    } catch {
      // An expired or unknown token is not an error worth showing anyone; it
      // just means this shopper needs a new basket.
      clearCartToken();
    }
  }
  const created = await api.post(`/${locale}/cart`, {});
  writeCartToken(created.data.token);
  return created.data;
}

export async function addItem(locale, { sku, quantity = 1, listId, listName, index }) {
  await ensureCart(locale);
  const response = await api.post(
    `/${locale}/cart/items`,
    {
      sku,
      quantity,
      // Section 5 list attribution: which listing the shopper came from. Sent
      // at add time because it cannot be reconstructed later.
      added_from_list_id: listId,
      added_from_list_name: listName,
      added_from_index: index,
    },
    auth(),
  );
  return response.data;
}

export async function setQuantity(locale, variantId, quantity) {
  const response = await api.patch(
    `/${locale}/cart/items/${variantId}`, { quantity }, auth(),
  );
  return response.data;
}

export async function removeItem(locale, variantId) {
  const response = await api.delete(`/${locale}/cart/items/${variantId}`, auth());
  return response.data;
}

export async function placeOrder(locale, payload, idempotencyKey) {
  const response = await api.post(
    `/${locale}/orders`,
    { ...payload, cart_token: readCartToken() },
    // The API refuses an order without this header. Generated once per attempt
    // so a double-click or a retry cannot create a second order.
    { headers: { 'Idempotency-Key': idempotencyKey } },
  );
  return response.data;
}
