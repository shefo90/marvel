import { keepPreviousData, useQuery } from '@tanstack/react-query';

import { listProducts } from '../services/catalog.service.js';

/**
 * The listing, paged and filtered by the server.
 *
 * `keepPreviousData` so paging does not blank the table between pages -- the
 * rows stay put and are replaced when the next page lands.
 */
export function useProducts(params) {
  return useQuery({
    queryKey: ['products', params],
    queryFn: () => listProducts(params),
    placeholderData: keepPreviousData,
  });
}
