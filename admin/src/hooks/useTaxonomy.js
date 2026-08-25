import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  createCategory,
  createCollection,
  getCategoryTree,
  getCollectionProducts,
  listCollections,
  setCollectionProducts,
  updateCategory,
  updateCollection,
  upsertCategoryTranslation,
  upsertCollectionTranslation,
} from '../services/taxonomy.service.js';

/**
 * Queries and mutations for the category tree and the collections.
 *
 * Both invalidate `['categories']` alongside their own key: the product form's
 * picker reads the flat level-2 list from a different endpoint, and a category
 * created here has to appear there without a reload, or the operator creates a
 * category and then cannot find it on the very next screen.
 */

export function useCategoryTree() {
  return useQuery({ queryKey: ['taxonomy', 'categories'], queryFn: getCategoryTree });
}

export function useCollections() {
  return useQuery({ queryKey: ['taxonomy', 'collections'], queryFn: listCollections });
}

export function useCollectionProducts(collectionId) {
  return useQuery({
    queryKey: ['taxonomy', 'collections', collectionId, 'products'],
    queryFn: () => getCollectionProducts(collectionId),
    enabled: Boolean(collectionId),
  });
}

export function useCategoryMutations() {
  const client = useQueryClient();
  const invalidate = () => {
    client.invalidateQueries({ queryKey: ['taxonomy', 'categories'] });
    client.invalidateQueries({ queryKey: ['categories'] });
  };

  return {
    create: useMutation({ mutationFn: createCategory, onSuccess: invalidate }),
    update: useMutation({
      mutationFn: ({ categoryId, values, expectedUpdatedAt }) =>
        updateCategory(categoryId, values, expectedUpdatedAt),
      onSuccess: invalidate,
    }),
    translate: useMutation({
      mutationFn: ({ categoryId, locale, values }) =>
        upsertCategoryTranslation(categoryId, locale, values),
      onSuccess: invalidate,
    }),
  };
}

export function useCollectionMutations() {
  const client = useQueryClient();
  const invalidate = () =>
    client.invalidateQueries({ queryKey: ['taxonomy', 'collections'] });

  return {
    create: useMutation({ mutationFn: createCollection, onSuccess: invalidate }),
    update: useMutation({
      mutationFn: ({ collectionId, values, expectedUpdatedAt }) =>
        updateCollection(collectionId, values, expectedUpdatedAt),
      onSuccess: invalidate,
    }),
    translate: useMutation({
      mutationFn: ({ collectionId, locale, values }) =>
        upsertCollectionTranslation(collectionId, locale, values),
      onSuccess: invalidate,
    }),
    setProducts: useMutation({
      mutationFn: ({ collectionId, productIds }) =>
        setCollectionProducts(collectionId, productIds),
      onSuccess: invalidate,
    }),
  };
}
