/**
 * Fold a title into a base slug the products CHECK will accept.
 *
 * `ck_products_slug_format` is ^[a-z0-9]+(-[a-z0-9]+)*$ -- ASCII, lower case,
 * single interior hyphens, no edges. This is a convenience for the operator,
 * not a validator: the field stays editable and the API refuses anything that
 * does not match regardless of what was typed here.
 *
 * Note the asymmetry with the *translation* slug, which is normalized on the
 * server against a denylist so Arabic survives intact. Base slugs are ASCII;
 * Arabic slugs live on the translation. An all-Arabic title therefore yields
 * nothing here, and the operator types the base slug themselves.
 */
export function slugify(raw) {
  return (raw ?? '')
    // Decompose, then drop the combining marks: "Café" folds to "cafe" rather
    // than losing the letter. \p{M} rather than a literal character range, so
    // this file stays pure ASCII -- the console here is cp1252 and invisible
    // combining characters in source are a trap.
    .normalize('NFD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/-{2,}/g, '-')
    .replace(/^-+|-+$/g, '');
}
