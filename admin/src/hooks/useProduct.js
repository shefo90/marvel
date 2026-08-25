import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  archiveProduct,
  getProduct,
  updateProduct,
} from '../services/catalog.service.js';

/**
 * The cache key for one product.
 *
 * String(id) because the id arrives as a string from the URL (useParams) and as
 * a number from the payload (product.id) -- ['product', '7'] and ['product', 7]
 * are different cache entries, so a mutation invalidating one left the other
 * showing stale data. That is not theoretical: generating variants returned 201
 * while the table it should have refreshed kept saying "No data".
 */
export const productKey = (id) => ['product', String(id)];

/**
 * One product, with its translations and variants -- the API returns all three
 * in a single call, so the editor never assembles a product from three
 * requests that can disagree with each other.
 */
export function useProduct(id) {
  return useQuery({
    queryKey: productKey(id),
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
    client.invalidateQueries({ queryKey: productKey(id) });
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
