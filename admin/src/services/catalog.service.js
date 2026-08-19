import { api } from './api.js';

/**
 * Every catalog call the back-office makes. Components never call axios.
 *
 * The admin endpoints are not locale-scoped, unlike the public ones: a product
 * has one editing screen showing both languages side by side, rather than one
 * URL per language.
 */
export async function listProducts({ page = 1, pageSize = 50, status, search } = {}) {
  // Omitted rather than sent empty: `status=` would be a value outside the
  // lifecycle enum and the route answers 422, and `search=` empty would filter
  // on a blank string.
  const params = { page, page_size: pageSize };
  if (status) params.status = status;
  if (search) params.search = search;

  const response = await api.get('/admin/products', { params });
  return response.data;
}

export async function createProduct(payload) {
  const response = await api.post('/admin/products', payload);
  return response.data;
}

export async function getProduct(id) {
  const response = await api.get(`/admin/products/${id}`);
  return response.data;
}

export async function updateProduct(id, payload) {
  const response = await api.patch(`/admin/products/${id}`, payload);
  return response.data;
}

export async function archiveProduct(id) {
  const response = await api.post(`/admin/products/${id}/archive`);
  return response.data;
}

export async function upsertTranslation(id, locale, payload) {
  const response = await api.put(`/admin/products/${id}/translations/${locale}`, payload);
  return response.data;
}

export async function getReadiness(id, locale) {
  const response = await api.get(`/admin/products/${id}/readiness`, {
    params: { locale },
  });
  return response.data;
}

export async function publishProduct(id, locale) {
  // Publishing is per language: Arabic and English are published
  // independently, so this always names one locale and never both.
  const response = await api.post(`/admin/products/${id}/publish`, null, {
    params: { locale },
  });
  return response.data;
}

export async function generateVariants(id, payload) {
  const response = await api.post(`/admin/products/${id}/variants`, payload);
  return response.data;
}

export async function updateVariant(variantId, payload) {
  const response = await api.patch(`/admin/variants/${variantId}`, payload);
  return response.data;
}
