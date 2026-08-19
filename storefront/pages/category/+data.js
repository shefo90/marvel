import { render } from 'vike/abort';

import {
  getCategory,
  listCategories,
  listProducts,
} from '../../services/catalog.service.js';
import { publicOrigin } from '../../services/api.js';
import { isLocale } from '../../utils/locales.js';

const COPY = {
  en: {
    filters: 'Filters', size: 'Size', colour: 'Colour', inStock: 'In stock only',
    sort: 'Sort', clear: 'Clear all', results: 'products', empty:
      'Nothing matches those filters yet. Try removing one.',
    sorts: {
      featured: 'Featured', newest: 'Newest',
      price_asc: 'Price, low to high', price_desc: 'Price, high to low',
    },
  },
  ar: {
    filters: 'تصفية', size: 'المقاس', colour: 'اللون', inStock: 'المتوفر فقط',
    sort: 'الترتيب', clear: 'مسح الكل', results: 'منتج', empty:
      'لا توجد نتائج مطابقة. جرّب إزالة أحد الفلاتر.',
    sorts: {
      featured: 'المميزة', newest: 'الأحدث',
      price_asc: 'السعر: من الأقل', price_desc: 'السعر: من الأعلى',
    },
  },
};

/**
 * Filters come from the query string, never from component state.
 *
 * That is what makes a filtered listing a real page: it can be linked, shared,
 * reloaded and — because the server renders it — indexed. Holding them in React
 * state would give every filter combination the same URL, which is the same
 * duplicate-address problem section 8A rejects for locales.
 */
function readFilters(search) {
  const params = new URLSearchParams(search ?? '');
  const page = Number.parseInt(params.get('page') ?? '1', 10);
  return {
    sizes: params.getAll('size'),
    colors: params.getAll('color'),
    inStock: params.get('in_stock') === '1',
    sort: params.get('sort') ?? 'featured',
    page: Number.isFinite(page) && page > 0 ? page : 1,
  };
}

export async function data(pageContext) {
  const { locale, slug } = pageContext.routeParams;
  if (!isLocale(locale)) throw render(404);

  const copy = COPY[locale] ?? COPY.en;
  const origin = publicOrigin();
  const filters = readFilters(pageContext.urlParsed?.searchOriginal);

  let category = null;
  let categories = [];
  try {
    [category, categories] = await Promise.all([
      getCategory(locale, slug),
      listCategories(locale),
    ]);
  } catch (error) {
    // A 404 from the API is a category that does not exist in this language,
    // which must be a 404 here too — not an empty page at HTTP 200.
    if (error?.response?.status === 404) throw render(404);
    throw error;
  }
  if (!category) throw render(404);

  let listing = { items: [], total: 0, facets: { sizes: [], colors: [] } };
  try {
    listing = await listProducts(locale, {
      category: slug,
      page: filters.page,
      pageSize: 24,
      sizes: filters.sizes,
      colors: filters.colors,
      inStock: filters.inStock,
      sort: filters.sort,
    });
  } catch {
    // A catalogue that will not load is an empty shelf, not a broken page.
  }

  return {
    locale,
    category,
    categories,
    listing,
    filters,
    copy,
    head: {
      title: category.seo_title ?? category.title,
      description: category.meta_description,
      canonical: `${origin}/${locale}${category.canonical_url ?? `/c/${slug}`}`.replace(
        `${origin}/${locale}/${locale}`,
        `${origin}/${locale}`,
      ),
      // A filtered view is the same shelf in a different order. Letting each
      // combination be indexed separately is how a shop generates thousands of
      // near-duplicate pages, so only the unfiltered page is indexable.
      noindex: filters.sizes.length > 0 || filters.colors.length > 0 || filters.page > 1,
      ogType: 'website',
    },
  };
}
