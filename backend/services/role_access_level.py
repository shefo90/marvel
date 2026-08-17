"""Role -> numeric access level.

The level is baked into the access token at login so endpoints gate on a numeric
comparison instead of a DB lookup.

Ladder for a single-warehouse Egyptian footwear retailer, highest privilege
first. Kept deliberately minimal — roles the business has no evidence of needing
are not invented here.

    admin       4   everything, including staff management and money corrections
    operations  3   orders, shipments, refunds, fulfilment state
    catalog     2   products, variants, categories, collections, SEO fields
    support     1   read orders/customers, assist shoppers, no money changes

NOTE: this ladder is a proposal and has not been confirmed by the business.
Role names match ``core.enums.StaffRole``; adding a role means adding it in both
places plus a migration for the users.role CHECK constraint.
"""

from core.enums import StaffRole

LEVELS = {
    StaffRole.admin.value: 4,
    StaffRole.operations.value: 3,
    StaffRole.catalog.value: 2,
    StaffRole.support.value: 1,
}

# Named thresholds so endpoints read as intent rather than magic numbers.
LEVEL_ADMIN = 4
LEVEL_OPERATIONS = 3
LEVEL_CATALOG = 2
LEVEL_SUPPORT = 1


def set_access_level(user) -> int:
    role = user.role.value if hasattr(user.role, "value") else user.role
    return LEVELS.get(role, 0)
