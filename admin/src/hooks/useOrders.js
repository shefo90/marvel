import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { getOrder, listOrders, updateOrderStatus } from '../services/order.service.js';

export function useOrders(params) {
  return useQuery({
    queryKey: ['orders', params],
    queryFn: () => listOrders(params),
    placeholderData: keepPreviousData,
  });
}

export function useOrder(orderNumber) {
  return useQuery({
    queryKey: ['order', orderNumber],
    queryFn: () => getOrder(orderNumber),
    enabled: orderNumber != null,
  });
}

export function useAdvanceOrder(orderNumber) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ status, reason }) => updateOrderStatus(orderNumber, status, reason),
    onSuccess: () => {
      // Both: the detail shows the new status and its history, and the listing
      // shows the order in a different bucket.
      client.invalidateQueries({ queryKey: ['order', orderNumber] });
      client.invalidateQueries({ queryKey: ['orders'] });
    },
  });
}
