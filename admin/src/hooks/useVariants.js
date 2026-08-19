import { useMutation } from '@tanstack/react-query';

import { generateVariants, updateVariant } from '../services/catalog.service.js';
import { useInvalidateProduct } from './useProduct.js';

export function useGenerateVariants(productId) {
  const invalidate = useInvalidateProduct(productId);
  return useMutation({
    mutationFn: (payload) => generateVariants(productId, payload),
    onSuccess: invalidate,
  });
}

/**
 * Editing a variant invalidates the *product*, not a variant query: variants
 * arrive as part of the product payload, so that one load is the only copy
 * there is to refresh.
 */
export function useUpdateVariant(productId) {
  const invalidate = useInvalidateProduct(productId);
  return useMutation({
    mutationFn: ({ variantId, values }) => updateVariant(variantId, values),
    onSuccess: invalidate,
  });
}
