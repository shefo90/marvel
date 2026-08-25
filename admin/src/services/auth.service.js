import { api } from './api.js';

/**
 * Staff sign-in. Returns the token pair verbatim -- AuthContext decides what to
 * keep and where, this only speaks HTTP.
 *
 * Staff and shoppers have separate endpoints on purpose: one endpoint that
 * guessed would disclose which table an email lives in, turning login into an
 * "is this address staff?" oracle.
 */
export async function staffLogin({ email, password }) {
  const response = await api.post('/en/auth/staff/login', { email, password });
  return response.data;
}
