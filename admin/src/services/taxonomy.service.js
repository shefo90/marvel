import { api } from './api.js';

/**
 * The category tree and the collections — the structure the whole shop is
 * organised around.
 *
 * Distinct from `category.service.js`, which reads a flat list of level-2
 * categories from an older endpoint purely to fill the product form's picker.
 * That one answers "where may this product go?"; this one answers "what is the
 * shape of the shop?", and only this one writes.
 *
 * **Every update sends `expected_updated_at`.** The backend treats the field as
 * optional so that callers written before it existed keep working, which means
 * the protection is only real if the client actually sends it. Doing that here,
 * once, rather than in each screen's submit handler is the whole reason this
 * layer exists — a screen that forgets is a screen that silently overwrites
 * another operator. See backend/services/optimistic_lock.py.
 */

export async function getCategoryTree() {
  const response = await api.get('/admin/taxonomy/categories');
  return response.data;
}

export async function createCategory(payload) {
  const response = await api.post('/admin/taxonomy/categories', payload);
  return response.data;
}

export async function updateCategory(categoryId, values, expectedUpdatedAt) {
  const response = await api.patch(`/admin/taxonomy/categories/${categoryId}`, {
    ...values,
    expected_updated_at: expectedUpdatedAt,
  });
  return response.data;
}

export async function upsertCategoryTranslation(categoryId, locale, payload) {
  const response = await api.put(
    `/admin/taxonomy/categories/${categoryId}/translations/${locale}`,
    payload,
  );
  return response.data;
}

export async function listCollections() {
  const response = await api.get('/admin/taxonomy/collections');
  return response.data;
}

export async function createCollection(payload) {
  const response = await api.post('/admin/taxonomy/collections', payload);
  return response.data;
}

export async function updateCollection(collectionId, values, expectedUpdatedAt) {
  const response = await api.patch(`/admin/taxonomy/collections/${collectionId}`, {
    ...values,
    expected_updated_at: expectedUpdatedAt,
  });
  return response.data;
}

export async function upsertCollectionTranslation(collectionId, locale, payload) {
  const response = await api.put(
    `/admin/taxonomy/collections/${collectionId}/translations/${locale}`,
    payload,
  );
  return response.data;
}

export async function getCollectionProducts(collectionId) {
  const response = await api.get(
    `/admin/taxonomy/collections/${collectionId}/products`,
  );
  return response.data.product_ids;
}

/**
 * Replace the membership wholesale, in order.
 *
 * The API takes the full list rather than a diff because position *is* the
 * data — it drives the collection's featured sort and section 5's `index` — and
 * an add/remove pair cannot express a reordering.
 */
export async function setCollectionProducts(collectionId, productIds) {
  const response = await api.put(
    `/admin/taxonomy/collections/${collectionId}/products`,
    { product_ids: productIds },
  );
  return response.data.product_ids;
}
