import { usePageContext } from './usePageContext.jsx';

/** Whatever the page's +data.js returned, on the server and after hydration. */
export function useData() {
  return usePageContext().data;
}
