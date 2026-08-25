import { createContext, useContext } from 'react';

/**
 * Vike's pageContext, made available to the tree.
 *
 * vike-react provides this, but this app renders itself (``+onRenderHtml`` /
 * ``+onRenderClient``) so that the <html> element's lang and dir are set from
 * the locale on every render and every client-side navigation. That control is
 * worth owning twenty lines for.
 */
const PageContext = createContext(null);

export function PageContextProvider({ pageContext, children }) {
  return <PageContext.Provider value={pageContext}>{children}</PageContext.Provider>;
}

export function usePageContext() {
  const value = useContext(PageContext);
  if (value === null) {
    throw new Error('usePageContext must be used inside a PageContextProvider');
  }
  return value;
}
