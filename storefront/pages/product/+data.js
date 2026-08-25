import { render } from 'vike/abort';

import { publicOrigin } from '../../services/api.js';
import { getProduct } from '../../services/catalog.service.js';
import { productJsonLd } from '../../utils/head.js';
import { isLocale } from '../../utils/locales.js';

export async function data(pageContext) {
  const { locale, slug } = pageContext.routeParams;
  if (!isLocale(locale)) throw render(404);

  let product;
  try {
    product = await getProduct(locale, decodeURIComponent(slug));
  } catch (failure) {
    // A product not published in THIS language is a 404 in this language, even
    // though it exists in the other. Serving the English page at the Arabic
    // address would be exactly the duplicate the hreflang cluster prevents.
    if (failure?.response?.status === 404) throw render(404);
    throw failure;
  }

  const origin = publicOrigin();
  // The API returns canonical_url as a PATH ("/en/products/x"), not an absolute
  // URL, and taking it verbatim shipped a relative canonical -- which search
  // engines ignore, making the tag decorative. The alternates a few lines down
  // were already absolutised the same way; the canonical was missed. Found by
  // reading the rendered HTML of a real product page, not by any test:
  // everything about a relative canonical looks correct in the markup.
  const canonicalPath = product.canonical_url || `/${locale}/products/${product.slug}`;
  const canonical = canonicalPath.startsWith('http')
    ? canonicalPath
    : `${origin}${canonicalPath}`;
  const image = product.images?.find((i) => i.is_primary) ?? product.images?.[0];

  // The API returns the cluster it knows to be published. Relative paths are
  // made absolute here, because a relative hreflang or canonical is ignored.
  const alternates = {};
  for (const [code, url] of Object.entries(product.alternates ?? {})) {
    alternates[code] = url.startsWith('http') ? url : `${origin}${url}`;
  }

  return {
    locale,
    product,
    head: {
      title: product.seo_title || product.title,
      description: product.meta_description ?? undefined,
      canonical,
      alternates,
      ogType: 'product',
      ogImage: product.og_image_url || (image ? `${origin}${image.url}` : undefined),
      noindex: product.is_indexable === false,
      jsonLd: productJsonLd(product, { canonical, locale }),
    },
  };
}
