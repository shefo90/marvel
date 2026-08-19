import { localeOf } from './locales.js';

/**
 * The head every page emits, built as data and rendered once.
 *
 * Section 8A treats these as a contract rather than decoration:
 *
 * * **canonical is absolute.** A relative canonical is ignored, and the whole
 *   point is to name one address out of several that could serve this content.
 * * **hreflang is reciprocal, or absent.** Each member of a cluster lists every
 *   member including itself. A cluster of one emits nothing — pointing a page
 *   at itself is noise — and a member that is not published is a 404 we would
 *   be advertising.
 * * **noindex is explicit** on per-shopper pages. A cart has nothing to index
 *   and differs for every visitor.
 */
function escape(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

export function buildHead(head = {}) {
  const {
    title,
    description,
    canonical,
    alternates = {},
    ogImage,
    ogType = 'website',
    noindex = false,
    jsonLd = null,
    locale = 'en',
  } = head;

  const tags = [];
  if (title) tags.push(`<title>${escape(title)}</title>`);
  if (description) {
    tags.push(`<meta name="description" content="${escape(description)}"/>`);
  }
  if (noindex) {
    tags.push('<meta name="robots" content="noindex, nofollow"/>');
  }
  if (canonical) {
    tags.push(`<link rel="canonical" href="${escape(canonical)}"/>`);
  }

  // Only a real cluster. One entry means the page is its own only version, and
  // a self-referential hreflang tells a crawler nothing it did not already know.
  const codes = Object.keys(alternates);
  if (codes.length > 1) {
    for (const code of codes.sort()) {
      const hreflang = localeOf(code).hreflang;
      tags.push(
        `<link rel="alternate" hreflang="${escape(hreflang)}" href="${escape(alternates[code])}"/>`,
      );
    }
    // x-default points at the language a shopper gets when none of theirs
    // matches. English, because it is the default locale.
    if (alternates.en) {
      tags.push(`<link rel="alternate" hreflang="x-default" href="${escape(alternates.en)}"/>`);
    }
  }

  tags.push(`<meta property="og:type" content="${escape(ogType)}"/>`);
  if (title) tags.push(`<meta property="og:title" content="${escape(title)}"/>`);
  if (description) {
    tags.push(`<meta property="og:description" content="${escape(description)}"/>`);
  }
  if (canonical) tags.push(`<meta property="og:url" content="${escape(canonical)}"/>`);
  if (ogImage) tags.push(`<meta property="og:image" content="${escape(ogImage)}"/>`);
  tags.push(`<meta property="og:locale" content="${escape(locale === 'ar' ? 'ar_EG' : 'en_US')}"/>`);

  if (jsonLd) {
    // JSON.stringify escapes nothing HTML-significant except via this guard:
    // a "</script>" inside a product description would otherwise close the tag.
    const serialized = JSON.stringify(jsonLd).replace(/</g, '\\u003c');
    tags.push(`<script type="application/ld+json">${serialized}</script>`);
  }

  return tags.join('\n    ');
}

/**
 * Schema.org Product, from what the API already returns.
 *
 * ``offers.price`` is the price actually asked, and ``availability`` mirrors
 * the variant's own value — section 8's Merchant diagnostics flag a mismatch
 * between structured data and the page, so both come from one source.
 */
export function productJsonLd(product, { canonical, locale }) {
  const variant = product.variants?.[0];
  const price = variant?.sale_price ?? variant?.price;
  const image = product.images?.find((i) => i.is_primary) ?? product.images?.[0];

  return {
    '@context': 'https://schema.org',
    '@type': 'Product',
    name: product.title,
    description: product.description ?? undefined,
    sku: variant?.sku,
    // The Merchant Center variant-grouping key, which is what productGroupID
    // means here too.
    productGroupID: product.item_group_id,
    brand: { '@type': 'Brand', name: product.brand },
    image: image ? [image.url] : undefined,
    inLanguage: locale,
    offers: price
      ? {
          '@type': 'Offer',
          url: canonical,
          priceCurrency: variant?.currency ?? 'EGP',
          price: String(price),
          availability:
            variant?.availability === 'in_stock'
              ? 'https://schema.org/InStock'
              : 'https://schema.org/OutOfStock',
        }
      : undefined,
  };
}
