import { useMutation, useQuery } from '@tanstack/react-query';

import {
  getReadiness,
  publishProduct,
  upsertTranslation,
} from '../services/catalog.service.js';
import { useInvalidateProduct } from './useProduct.js';

/**
 * What still blocks one language from publishing.
 *
 * Asked of the API rather than derived here. The API mirrors the database's own
 * CHECK constraints, and a second implementation in the browser is exactly the
 * drift that let an empty title publish in the first place -- two copies of one
 * rule that disagreed.
 */
export function useReadiness(id, locale) {
  return useQuery({
    queryKey: ['readiness', id, locale],
    queryFn: () => getReadiness(id, locale),
    enabled: id != null && locale != null,
  });
}

export function useSaveTranslation(id) {
  const invalidate = useInvalidateProduct(id);
  return useMutation({
    mutationFn: ({ locale, values }) => upsertTranslation(id, locale, values),
    onSuccess: invalidate,
  });
}

export function usePublish(id) {
  const invalidate = useInvalidateProduct(id);
  return useMutation({
    mutationFn: (locale) => publishProduct(id, locale),
    onSuccess: invalidate,
  });
}
