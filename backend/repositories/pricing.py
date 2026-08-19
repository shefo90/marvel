"""What a basket costs. One implementation, called by both cart and checkout.

**Why one function and not two.** The worst defect in this project's history was
two customer-identity normalizers that disagreed: one shopper resolved into two
``customers`` rows and every lifetime-value figure was wrong, while each
individual test passed. Pricing has the identical shape — if the cart prices one
way and checkout another, the shopper sees one number and is charged a different
one, which is exactly the "price mismatch" Merchant Center diagnostics flag.
``services/identity.py`` carries the same warning for the same reason.

**The money shape, which is easy to get backwards.** A markdown is not a
campaign cost:

    unit_list_price   the catalogue price
    unit_price        what the catalogue currently asks (the sale price if any)
    discount_amount   what a PROMOTION took off on top of that

so a markdown reads as ``unit_list_price - unit_price`` and never reaches
``orders.promotion_cost_total``, which sums only ``discount_source =
'promotion'``. Section 4.4 of the admin design says this in words; this module
is where it becomes arithmetic.

**Resolution order** (section 4.6), per line:

1. the best per-unit price — the lowest of the list price, the sale price, and
   each matching percentage/fixed promotion applied to the list price
2. BOGO across every matching line, ranking units by price descending and
   discounting the cheapest in each complete chunk
3. whichever of the two gave the shopper more. **A line carries one promotion,
   never two.**

Step 3 compares at line level rather than searching cart-wide combinations. That
is a deliberate simplification: it is deterministic, never worse than either
offer alone, and the operator can explain it to a customer — which matters more
here than optimality. Its one imprecision is that a line choosing the per-unit
offer does not send the BOGO chunking back to be recomputed without it.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from models.collection_products import CollectionProduct
from models.products import Product
from models.promotion_targets import PromotionTarget
from models.promotions import Promotion

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(CENT)


@dataclass(frozen=True)
class PricedLine:
    """One basket line, priced. Every field maps to an ``order_items`` column."""

    variant_id: int
    quantity: int
    unit_list_price: Decimal
    unit_price: Decimal
    line_subtotal: Decimal
    discount_amount: Decimal
    line_total: Decimal
    promotion_id: int | None
    discount_source: str | None


def _live_promotions(db: Session, now: datetime) -> list[Promotion]:
    """Active promotions whose window contains ``now``.

    ``is_active`` and the window are independent on purpose: turning an offer
    off must not require editing its dates.
    """
    return list(
        db.execute(
            select(Promotion).where(
                Promotion.is_active.is_(True),
                or_(Promotion.starts_at.is_(None), Promotion.starts_at <= now),
                or_(Promotion.ends_at.is_(None), Promotion.ends_at > now),
            )
        ).scalars()
    )


def _targets_by_promotion(db: Session, promotion_ids: list[int]) -> dict[int, list[PromotionTarget]]:
    if not promotion_ids:
        return {}
    grouped: dict[int, list[PromotionTarget]] = {}
    for target in db.execute(
        select(PromotionTarget).where(PromotionTarget.promotion_id.in_(promotion_ids))
    ).scalars():
        grouped.setdefault(target.promotion_id, []).append(target)
    return grouped


def _collection_ids(db: Session, product_ids: set[int]) -> dict[int, set[int]]:
    if not product_ids:
        return {}
    memberships: dict[int, set[int]] = {}
    for product_id, collection_id in db.execute(
        select(CollectionProduct.product_id, CollectionProduct.collection_id).where(
            CollectionProduct.product_id.in_(product_ids)
        )
    ).all():
        memberships.setdefault(product_id, set()).add(collection_id)
    return memberships


def _matches(targets, variant, product, collection_ids: set[int]) -> bool:
    """Does this promotion apply to this variant?

    An empty target list matches nothing, and that is the whole point:
    discounting the catalogue requires choosing ``all`` explicitly, so a
    half-saved offer cannot mark everything down.
    """
    for target in targets:
        kind = target.target_type
        kind = kind.value if hasattr(kind, "value") else kind
        if kind == "all":
            return True
        if kind == "variant" and target.target_id == variant.id:
            return True
        if kind == "product" and target.target_id == variant.product_id:
            return True
        if kind == "category" and product is not None and target.target_id == product.category_id:
            return True
        if kind == "collection" and target.target_id in collection_ids:
            return True
    return False


def _per_unit_price(promotion: Promotion, list_price: Decimal) -> Decimal | None:
    """What one unit costs under a percentage or fixed promotion.

    Computed off the *list* price, per section 4.6 — the promotion competes with
    the sale price rather than compounding on it. Never below zero: a fixed 600
    off a 500 shoe is 500 off, not a refund.
    """
    kind = promotion.type.value if hasattr(promotion.type, "value") else promotion.type
    if kind == "percentage":
        factor = (Decimal("100") - Decimal(str(promotion.discount_percent))) / Decimal("100")
        return max(_money(list_price * factor), ZERO)
    if kind == "fixed":
        return max(_money(list_price - Decimal(str(promotion.discount_amount))), ZERO)
    return None


def price_basket(db: Session, items, *, now: datetime | None = None) -> list[PricedLine]:
    """Price ``[(variant, quantity), ...]``, resolving offers across the basket.

    ``now`` is injectable so a test can stand at a chosen moment in a
    promotion's window rather than depending on the clock.
    """
    if not items:
        return []

    now = now or datetime.now(timezone.utc)
    promotions = _live_promotions(db, now)
    targets = _targets_by_promotion(db, [promotion.id for promotion in promotions])

    variants = [variant for variant, _ in items]
    product_ids = {variant.product_id for variant in variants}
    products = {
        product.id: product
        for product in db.execute(
            select(Product).where(Product.id.in_(product_ids))
        ).scalars()
    }
    memberships = _collection_ids(db, product_ids)

    # --- per line: catalogue price, and the best per-unit promotion ----------
    catalogue: dict[int, Decimal] = {}
    list_prices: dict[int, Decimal] = {}
    unit_choice: dict[int, tuple[Decimal, int | None]] = {}
    applicable: dict[int, list[Promotion]] = {}

    for variant, _quantity in items:
        list_price = _money(variant.price)
        sale = _money(variant.sale_price) if variant.sale_price is not None else None
        catalogue_price = sale if sale is not None and sale < list_price else list_price
        list_prices[variant.id] = list_price
        catalogue[variant.id] = catalogue_price

        matching = [
            promotion
            for promotion in promotions
            if _matches(
                targets.get(promotion.id, []),
                variant,
                products.get(variant.product_id),
                memberships.get(variant.product_id, set()),
            )
        ]
        applicable[variant.id] = matching

        best_price, best_id = catalogue_price, None
        for promotion in matching:
            candidate = _per_unit_price(promotion, list_price)
            if candidate is not None and candidate < best_price:
                best_price, best_id = candidate, promotion.id
        unit_choice[variant.id] = (best_price, best_id)

    # --- BOGO, ranked across every line the promotion targets ---------------
    bogo_saving: dict[int, tuple[Decimal, int | None]] = {
        variant.id: (ZERO, None) for variant in variants
    }

    for promotion in promotions:
        kind = promotion.type.value if hasattr(promotion.type, "value") else promotion.type
        if kind != "bogo":
            continue

        units: list[tuple[Decimal, int]] = []
        for variant, quantity in items:
            if promotion not in applicable[variant.id]:
                continue
            units.extend([(catalogue[variant.id], variant.id)] * quantity)
        if not units:
            continue

        # Descending, so the discounted unit is the cheapest of its group: the
        # shopper does not get the expensive shoe free by adding a cheap one.
        units.sort(key=lambda unit: unit[0], reverse=True)
        chunk = promotion.buy_quantity + promotion.get_quantity
        share = Decimal(str(promotion.get_discount_percent)) / Decimal("100")

        per_variant: dict[int, Decimal] = {}
        for index, (price, variant_id) in enumerate(units):
            position_in_chunk = index % chunk
            # Only complete chunks pay out, and only their trailing "get" units.
            if position_in_chunk < promotion.buy_quantity:
                continue
            if index - position_in_chunk + chunk > len(units):
                continue
            per_variant[variant_id] = per_variant.get(variant_id, ZERO) + _money(price * share)

        for variant_id, saving in per_variant.items():
            if saving > bogo_saving[variant_id][0]:
                bogo_saving[variant_id] = (saving, promotion.id)

    # --- keep whichever gave more, and never both ---------------------------
    lines: list[PricedLine] = []
    for variant, quantity in items:
        catalogue_price = catalogue[variant.id]
        unit_price_after, unit_promotion_id = unit_choice[variant.id]
        per_unit_total = _money((catalogue_price - unit_price_after) * quantity)
        bogo_total, bogo_promotion_id = bogo_saving[variant.id]

        if bogo_total > per_unit_total:
            discount, promotion_id = bogo_total, bogo_promotion_id
        else:
            discount, promotion_id = per_unit_total, unit_promotion_id

        line_subtotal = _money(catalogue_price * quantity)
        discount = min(discount, line_subtotal)

        if promotion_id is not None and discount > ZERO:
            source = "promotion"
        elif catalogue_price < list_prices[variant.id]:
            source = "sale_price"
        else:
            source = None
        if source != "promotion":
            promotion_id = None

        lines.append(
            PricedLine(
                variant_id=variant.id,
                quantity=quantity,
                unit_list_price=list_prices[variant.id],
                unit_price=catalogue_price,
                line_subtotal=line_subtotal,
                discount_amount=discount,
                line_total=_money(line_subtotal - discount),
                promotion_id=promotion_id,
                discount_source=source,
            )
        )
    return lines
