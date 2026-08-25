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

export async function uploadImage(productId, { file, altText, variantId }) {
  // FormData, and deliberately no explicit Content-Type: axios sets it with the
  // multipart boundary, and setting it by hand loses the boundary and produces
  // a request the server cannot parse.
  const form = new FormData();
  form.append('file', file);
  form.append('alt_text', altText);
  if (variantId != null) form.append('variant_id', String(variantId));

  const response = await api.post(`/admin/products/${productId}/images`, form);
  return response.data;
}

export async function setPrimaryImage(imageId) {
  const response = await api.patch(`/admin/images/${imageId}/primary`);
  return response.data;
}

export async function reorderImages(productId, imageIds, variantId = null) {
  // The whole set, every time: the API refuses a partial list because the
  // omitted rows would keep positions the new ones collide with.
  const response = await api.put(`/admin/products/${productId}/images/order`, {
    image_ids: imageIds,
    variant_id: variantId,
  });
  return response.data;
}

export async function deleteImage(imageId) {
  await api.delete(`/admin/images/${imageId}`);
}

export async function upsertImageAlt(imageId, locale, altText) {
  const response = await api.put(`/admin/images/${imageId}/alt/${locale}`, {
    alt_text: altText,
  });
  return response.data;
}
