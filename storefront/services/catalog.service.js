import { api } from './api.js';

/**
 * Catalog reads.
 *
 * Filters are sent as repeated query parameters (`?size=38&size=39`), which is
 * what the API's `list[str]` parameters expect. Codes go over the wire, never
 * labels: the Arabic page displays "أسود" but the column holds "black", so
 * sending what the shopper sees would match nothing.
 */
export async function listProducts(locale, options = {}) {
  const {
    page = 1,
    pageSize = 24,
    category,
    collection,
    sizes = [],
    colors = [],
    minPrice,
    maxPrice,
    inStock = false,
    sort,
  } = options;

  const response = await api.get(`/${locale}/products`, {
    params: {
      page,
      page_size: pageSize,
      category,
      collection,
      size: sizes,
      color: colors,
      min_price: minPrice,
      max_price: maxPrice,
      in_stock: inStock || undefined,
      sort,
    },
    // Axios defaults to `size[]=38`, which FastAPI reads as a parameter named
    // "size[]" and ignores. Repeating the bare key is what it actually parses.
    paramsSerializer: { indexes: null },
  });
  return response.data;
}

export async function getProduct(locale, slug) {
  const response = await api.get(`/${locale}/products/${encodeURIComponent(slug)}`);
  return response.data;
}

/** The navigation menu. Always exactly two levels — the schema cannot hold a third. */
export async function listCategories(locale) {
  const response = await api.get(`/${locale}/categories`);
  return response.data;
}

export async function getCategory(locale, slug) {
  const response = await api.get(`/${locale}/categories/${encodeURIComponent(slug)}`);
  return response.data;
}

export async function listCollections(locale) {
  const response = await api.get(`/${locale}/collections`);
  return response.data;
}

export async function getCollection(locale, slug) {
  const response = await api.get(`/${locale}/collections/${encodeURIComponent(slug)}`);
  return response.data;
}
