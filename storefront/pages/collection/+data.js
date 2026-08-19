import { render } from 'vike/abort';

import {
  getCollection,
  listCategories,
  listProducts,
} from '../../services/catalog.service.js';
import { publicOrigin } from '../../services/api.js';
import { isLocale } from '../../utils/locales.js';

const COPY = {
  en: {
    filters: 'Filters', size: 'Size', colour: 'Colour', inStock: 'In stock only',
    sort: 'Sort', clear: 'Clear all', results: 'products',
    empty: 'Nothing matches those filters yet. Try removing one.',
    sorts: {
      featured: 'Featured', newest: 'Newest',
      price_asc: 'Price, low to high', price_desc: 'Price, high to low',
    },
  },
  ar: {
    filters: 'تصفية', size: 'المقاس', colour: 'اللون', inStock: 'المتوفر فقط',
    sort: 'الترتيب', clear: 'مسح الكل', results: 'منتج',
    empty: 'لا توجد نتائج مطابقة. جرّب إزالة أحد الفلاتر.',
    sorts: {
      featured: 'المميزة', newest: 'الأحدث',
      price_asc: 'السعر: من الأقل', price_desc: 'السعر: من الأعلى',
    },
  },
};

function readFilters(search) {
  const params = new URLSearchParams(search ?? '');
  const page = Number.parseInt(params.get('page') ?? '1', 10);
  return {
    sizes: params.getAll('size'),
    colors: params.getAll('color'),
    inStock: params.get('in_stock') === '1',
    // "Featured" means something here that it does not on a category page: it
    // is the order the operator arranged the collection in, which is the whole
    // reason a collection exists.
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

  let collection = null;
  let categories = [];
  try {
    [collection, categories] = await Promise.all([
      getCollection(locale, slug),
      listCategories(locale),
    ]);
  } catch (error) {
    if (error?.response?.status === 404) throw render(404);
    throw error;
  }
  if (!collection) throw render(404);

  let listing = { items: [], total: 0, facets: { sizes: [], colors: [] } };
  try {
    listing = await listProducts(locale, {
      collection: slug,
      page: filters.page,
      pageSize: 24,
      sizes: filters.sizes,
      colors: filters.colors,
      inStock: filters.inStock,
      sort: filters.sort,
    });
  } catch {
    // An edit that will not load is an empty shelf, not a broken page.
  }

  return {
    locale,
    collection,
    categories,
    listing,
    filters,
    copy,
    head: {
      title: collection.seo_title ?? collection.title,
      description: collection.meta_description,
      canonical: `${origin}/${locale}/edit/${slug}`,
      noindex: filters.sizes.length > 0 || filters.colors.length > 0 || filters.page > 1,
      ogType: 'website',
    },
  };
}
