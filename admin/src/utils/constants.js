// Mirrors backend/core/enums.py. A value outside these lists is refused by the
// API schema with a 422 -- and the columns behind them are
// SAEnum(native_enum=False) with no CHECK, so a value that slips past the
// schema is written and then makes the row unreadable.
export const PRODUCT_STATUSES = ['draft', 'active', 'archived'];
// core/enums.py OrderStatus. The repository enforces which moves are legal;
// this list is only what the filter offers.
export const ORDER_STATUSES = [
  'pending', 'confirmed', 'processing', 'shipped', 'delivered', 'cancelled', 'returned',
];
// Mirrors _ALLOWED in repositories/admin_orders.py. The API refuses anything
// else with a 409 -- this exists so the UI does not offer a button that cannot
// work, not as a second source of truth.
export const ORDER_NEXT = {
  pending: ['confirmed', 'cancelled'],
  confirmed: ['processing', 'cancelled'],
  processing: ['shipped', 'cancelled'],
  shipped: ['delivered', 'returned', 'cancelled'],
  delivered: ['returned'],
  cancelled: [],
  returned: [],
};
export const LEVEL_OPERATIONS = 3;
export const CONDITIONS = ['new', 'refurbished', 'used'];
export const GENDERS = ['male', 'female', 'unisex'];
export const AGE_GROUPS = ['newborn', 'infant', 'toddler', 'kids', 'adult'];
export const AVAILABILITIES = ['in_stock', 'out_of_stock', 'preorder', 'backorder'];

// Egypt only, English and Arabic only -- a locked decision, not a placeholder.
// Hardcoded rather than fetched from `locales`: an admin that cannot start
// until a second request returns is worse than one that knows its two
// languages.
export const LOCALES = [
  { code: 'en', label: 'English', dir: 'ltr' },
  { code: 'ar', label: 'Arabic', dir: 'rtl' },
];

// services/role_access_level.py. Compared numerically, never by name.
export const LEVEL_CATALOG = 2;
export const LEVEL_ADMIN = 4;
