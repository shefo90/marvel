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
