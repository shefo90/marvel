/**
 * Global Vike configuration.
 *
 * ``passToClient`` is the contract between the render and the hydration: data
 * fetched on the server is serialized into the page so the browser does not
 * refetch it on first paint. Anything not listed here is server-only, which is
 * where secrets stay.
 */
export default {
  passToClient: ['data', 'routeParams', 'locale'],
  clientRouting: true,
  hydrationCanBeAborted: true,
};
