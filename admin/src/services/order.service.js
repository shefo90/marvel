import { api } from './api.js';

/**
 * Orders are addressed by order number, never by id: it is the immutable
 * commerce identity, the GA4/Ads transaction_id, and the thing a shopper
 * quotes on the phone.
 */
export async function listOrders({ page = 1, pageSize = 50, status, search } = {}) {
  const params = { page, page_size: pageSize };
  if (status) params.status = status;
  if (search) params.search = search;
  const response = await api.get('/admin/orders', { params });
  return response.data;
}

export async function getOrder(orderNumber) {
  const response = await api.get(`/admin/orders/${orderNumber}`);
  return response.data;
}

export async function updateOrderStatus(orderNumber, status, reason) {
  const response = await api.patch(`/admin/orders/${orderNumber}/status`, {
    status,
    reason: reason || null,
  });
  return response.data;
}
