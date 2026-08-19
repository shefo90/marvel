import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  archiveProduct,
  getProduct,
  updateProduct,
} from '../services/catalog.service.js';

/**
 * One product, with its translations and variants -- the API returns all three
 * in a single call, so the editor never assembles a product from three
 * requests that can disagree with each other.
 */
export function useProduct(id) {
  return useQuery({
    queryKey: ['product', id],
    queryFn: () => getProduct(id),
    enabled: id != null,
  });
}

/**
 * Every mutation invalidates both the product and the listing.
 *
 * The listing shows status and per-language publish state, so a change made
 * here is visible there. Leaving it stale is how an operator publishes a
 * language, returns to the list, sees "draft", and publishes it again.
 */
export function useInvalidateProduct(id) {
  const client = useQueryClient();
  return () => {
    client.invalidateQueries({ queryKey: ['product', id] });
    client.invalidateQueries({ queryKey: ['products'] });
  };
}

export function useUpdateProduct(id) {
  const invalidate = useInvalidateProduct(id);
  return useMutation({
    mutationFn: (payload) => updateProduct(id, payload),
    onSuccess: invalidate,
  });
}

export function useArchiveProduct(id) {
  const invalidate = useInvalidateProduct(id);
  return useMutation({ mutationFn: () => archiveProduct(id), onSuccess: invalidate });
}
