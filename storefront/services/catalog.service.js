import { api } from './api.js';

export async function listProducts(locale, { page = 1, pageSize = 24 } = {}) {
  const response = await api.get(`/${locale}/products`, {
    params: { page, page_size: pageSize },
  });
  return response.data;
}

export async function getProduct(locale, slug) {
  const response = await api.get(`/${locale}/products/${encodeURIComponent(slug)}`);
  return response.data;
}
