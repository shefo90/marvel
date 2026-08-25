import { api } from './api.js';

/**
 * The level-2 categories a product may attach to.
 *
 * Level 2 is the only level `products` accepts -- category_level is a generated
 * column pinned to 2 with a composite FK -- so this list is the whole set of
 * legal choices, not a filtered view of a larger one.
 */
export async function listCategories() {
  const response = await api.get('/admin/categories');
  return response.data;
}
