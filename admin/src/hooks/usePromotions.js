import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  createPromotion,
  listPromotions,
  updatePromotion,
} from '../services/promotion.service.js';

export function usePromotions() {
  return useQuery({ queryKey: ['promotions'], queryFn: listPromotions });
}

export function usePromotionMutations() {
  const client = useQueryClient();
  const invalidate = () => client.invalidateQueries({ queryKey: ['promotions'] });

  return {
    create: useMutation({ mutationFn: createPromotion, onSuccess: invalidate }),
    update: useMutation({
      mutationFn: ({ promotionId, values }) => updatePromotion(promotionId, values),
      onSuccess: invalidate,
    }),
  };
}
