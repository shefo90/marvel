import { render } from 'vike/abort';

import {
  listCategories,
  listCollections,
  listProducts,
} from '../../services/catalog.service.js';
import { publicOrigin } from '../../services/api.js';
import { isLocale } from '../../utils/locales.js';

const COPY = {
  en: {
    heading: 'New in',
    description: 'Everything just added to the shop, newest first.',
    filters: 'Filters', size: 'Size', colour: 'Colour', inStock: 'In stock only',
    sort: 'Sort', clear: 'Clear all', results: 'products', empty:
      'Nothing matches those filters yet. Try removing one.',
    sorts: {
      featured: 'Featured', newest: 'Newest',
      price_asc: 'Price, low to high', price_desc: 'Price, high to low',
    },
  },
  ar: {
    heading: 'وصل حديثًا',
    description: 'كل ما أُضيف للمتجر حديثًا، الأحدث أولًا.',
    filters: 'تصفية', size: 'المقاس', colour: 'اللون', inStock: 'المتوفر فقط',
    sort: 'الترتيب', clear: 'مسح الكل', results: 'منتج', empty:
      'لا توجد نتائج مطابقة. جرّب إزالة أحد الفلاتر.',
    sorts: {
      featured: 'المميزة', newest: 'الأحدث',
      price_asc: 'السعر: من الأقل', price_desc: 'السعر: من الأعلى',
    },
  },
};

// Same query-string-driven filters as the category page, and for the same
// reason: a filtered/sorted view needs its own linkable, indexable address
// rather than living in component state.
function readFilters(search) {
  const params = new URLSearchParams(search ?? '');
  const page = Number.parseInt(params.get('page') ?? '1', 10);
  return {
    sizes: params.getAll('size'),
    colors: params.getAll('color'),
    inStock: params.get('in_stock') === '1',
    // Defaults to newest rather than "featured" -- that is the entire point
    // of this page, and a first-time visitor who never touches Sort should
    // still see it.
    sort: params.get('sort') ?? 'newest',
    page: Number.isFinite(page) && page > 0 ? page : 1,
  };
}

export async function data(pageContext) {
  const { locale } = pageContext.routeParams;
  if (!isLocale(locale)) throw render(404);

  const copy = COPY[locale] ?? COPY.en;
  const origin = publicOrigin();
  const filters = readFilters(pageContext.urlParsed?.searchOriginal);

  const [categories, collections] = await Promise.all([
    listCategories(locale).catch(() => []),
    listCollections(locale).catch(() => []),
  ]);

  let listing = { items: [], total: 0, facets: { sizes: [], colors: [] } };
  try {
    listing = await listProducts(locale, {
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
    categories,
    collections,
    listing,
    filters,
    copy,
    head: {
      title: copy.heading,
      description: copy.description,
      canonical: `${origin}/${locale}/new-in`,
      alternates: { en: `${origin}/en/new-in`, ar: `${origin}/ar/new-in` },
      // Same reasoning as the category page: only the unfiltered, first page
      // is the canonical shelf. Every filter combination is the same shelf in
      // a different order, and indexing each one is how a shop generates
      // thousands of near-duplicate pages.
      noindex: filters.sizes.length > 0 || filters.colors.length > 0 || filters.page > 1,
      ogType: 'website',
    },
  };
}
