// The locale is a required path segment, so "/" matches nothing here and the
// server redirects it. There is no locale-less version of any page: a single
// address must always resolve to a single language.
export default '/@locale';
