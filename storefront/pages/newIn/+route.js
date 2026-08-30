// "New in" is a fixed view over the whole catalogue, not a translated entity
// like a category or a collection -- there is no per-language slug to look up,
// so (like /search) the path segment itself stays a single, untranslated word
// in both locales.
export default '/@locale/new-in';
