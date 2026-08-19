import { api } from './api.js';

/**
 * Offers. Created with their targets in one call: a promotion without targets
 * discounts nothing, so saving the two halves separately would leave a row that
 * looks live and does nothing.
 */
export async function listPromotions() {
  const response = await api.get('/admin/promotions');
  return response.data;
}

export async function createPromotion(payload) {
  const response = await api.post('/admin/promotions', payload);
  return response.data;
}

export async function updatePromotion(promotionId, payload) {
  const response = await api.patch(`/admin/promotions/${promotionId}`, payload);
  return response.data;
}
