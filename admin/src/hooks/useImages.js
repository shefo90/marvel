import { useMutation } from '@tanstack/react-query';

import {
  deleteImage,
  reorderImages,
  setPrimaryImage,
  upsertImageAlt,
  uploadImage,
} from '../services/catalog.service.js';
import { useInvalidateProduct } from './useProduct.js';

/**
 * Every image mutation, each invalidating the product.
 *
 * Images arrive as part of the product payload rather than from a query of
 * their own, so that one load is the only copy there is to refresh -- and the
 * listing shows an image count, which is why the listing is invalidated too.
 */
export function useImageMutations(productId) {
  const invalidate = useInvalidateProduct(productId);

  return {
    upload: useMutation({
      mutationFn: (input) => uploadImage(productId, input),
      onSuccess: invalidate,
    }),
    makePrimary: useMutation({ mutationFn: setPrimaryImage, onSuccess: invalidate }),
    reorder: useMutation({
      mutationFn: ({ imageIds, variantId }) =>
        reorderImages(productId, imageIds, variantId),
      onSuccess: invalidate,
    }),
    remove: useMutation({ mutationFn: deleteImage, onSuccess: invalidate }),
    setAlt: useMutation({
      mutationFn: ({ imageId, locale, altText }) =>
        upsertImageAlt(imageId, locale, altText),
      onSuccess: invalidate,
    }),
  };
}
