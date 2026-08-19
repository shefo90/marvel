import axios from 'axios';

/**
 * The one axios instance, and the only place that knows about tokens.
 *
 * Blank base URL by default: Vite proxies `/api` to the API in development and
 * the two share an origin in production, so the browser never makes a
 * cross-origin request and the API needs no CORS middleware. Set
 * VITE_API_BASE_URL only when the admin moves to its own subdomain.
 *
 * No React in this file. Components never call axios directly — the project
 * structure document is explicit about that, and it is what lets the refresh
 * dance below live in exactly one place.
 */
const BASE_URL = import.meta.env?.VITE_API_BASE_URL || '/api';

// The admin interface is English; this segment is the API's locale prefix, not
// a user-facing choice. Open question 3 of the back-office design.
const REFRESH_URL = `${BASE_URL}/en/auth/staff/refresh`;

export const api = axios.create({ baseURL: BASE_URL });

let tokens = { accessToken: null, refreshToken: null };
let handlers = {};
let refreshInFlight = null;

/** Called by AuthContext whenever the session changes. */
export function setAuthTokens(next) {
  tokens = next ?? { accessToken: null, refreshToken: null };
}

/** `onRefreshed` feeds a rotated pair back into React; `onFailure` signs out. */
export function setAuthHandlers(next) {
  handlers = next ?? {};
}

export class ApiError extends Error {
  constructor({ status, message, blockers, fieldErrors }) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.blockers = blockers;
    this.fieldErrors = fieldErrors;
  }
}

/**
 * FastAPI puts three different shapes in `detail`, and each needs different
 * treatment in the UI:
 *
 *   "slug already in use"                     a 409 or a guard  -> a sentence
 *   [{code, message}]                         publish 422       -> blocker list
 *   [{loc, msg, type}]                        pydantic 422      -> field errors
 *
 * Assuming any one of them renders the other two as "[object Object]".
 */
export function normalizeError(error) {
  const status = error?.response?.status ?? 0;
  const detail = error?.response?.data?.detail;

  if (Array.isArray(detail)) {
    if (detail.length > 0 && detail[0] && 'code' in detail[0]) {
      return new ApiError({
        status,
        message: detail.map((blocker) => blocker.message).join(' '),
        blockers: detail,
        fieldErrors: {},
      });
    }

    const fieldErrors = {};
    for (const item of detail) {
      // loc is ["body", "item_group_id"] or ["query", "status"]; the field is
      // the last segment. Nested bodies would need the tail joined, but no
      // admin payload nests.
      const field = Array.isArray(item?.loc) ? item.loc[item.loc.length - 1] : null;
      if (field != null && !(field in fieldErrors)) fieldErrors[field] = item.msg;
    }
    return new ApiError({
      status,
      message: 'Please correct the highlighted fields.',
      blockers: [],
      fieldErrors,
    });
  }

  if (typeof detail === 'string' && detail.length > 0) {
    return new ApiError({ status, message: detail, blockers: [], fieldErrors: {} });
  }

  return new ApiError({
    status,
    message: error?.message || 'Something went wrong.',
    blockers: [],
    fieldErrors: {},
  });
}

api.interceptors.request.use((config) => {
  if (tokens.accessToken) {
    config.headers.Authorization = `Bearer ${tokens.accessToken}`;
  }
  return config;
});

/**
 * One rotation at a time, shared by every waiter.
 *
 * Rotation revokes the token it was handed, so two concurrent refreshes mean
 * the second presents a token that was just revoked — it fails, and the
 * operator is signed out mid-task for no reason. `axios` bare rather than the
 * instance above, so a failing refresh cannot recurse into this interceptor.
 */
function refreshTokens() {
  if (refreshInFlight === null) {
    refreshInFlight = axios
      .post(REFRESH_URL, null, {
        headers: { Authorization: `Bearer ${tokens.refreshToken}` },
      })
      .then((response) => {
        setAuthTokens({
          accessToken: response.data.access_token,
          refreshToken: response.data.refresh_token,
        });
        handlers.onRefreshed?.(response.data);
        return response.data;
      })
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error?.config;
    const isExpired = error?.response?.status === 401;
    // No refresh token means this is a login attempt with bad credentials, not
    // an expired session. Refreshing there would report the wrong error to
    // someone who simply mistyped their password.
    const canRetry = isExpired && original && !original._retried && tokens.refreshToken;

    if (canRetry) {
      original._retried = true;
      try {
        await refreshTokens();
        return await api(original);
      } catch (refreshFailure) {
        handlers.onFailure?.();
        return Promise.reject(normalizeError(refreshFailure));
      }
    }

    return Promise.reject(normalizeError(error));
  },
);
