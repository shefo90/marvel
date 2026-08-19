import { useQuery } from '@tanstack/react-query';

import { listCategories } from '../services/category.service.js';

/**
 * The taxonomy changes about never, so this is cached for the session rather
 * than refetched every time the create form opens.
 */
export function useCategories() {
  return useQuery({
    queryKey: ['categories'],
    queryFn: listCategories,
    staleTime: 30 * 60 * 1000,
  });
}
