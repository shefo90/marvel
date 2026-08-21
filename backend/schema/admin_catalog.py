"""Admin catalog contracts. No logic here — see repositories/admin_catalog.py.

The enum-typed fields are typed against ``core.enums`` rather than ``str``
deliberately. Those columns are ``SAEnum(native_enum=False)`` with no CHECK
behind them, so an unknown value is *written* happily and then raises
LookupError on every subsequent read of the row — the product becomes
unloadable. Rejecting it at the boundary is the only place that costs nothing.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from core.enums import (
    AgeGroup,
    Gender,
    ProductCondition,
    PromotionTargetType,
    PromotionType,
)


class translation_state(BaseModel):
    """Per-locale publish state, so the operator can see what is unfinished."""

    locale: str
    is_published: bool
    is_complete: bool


class admin_product_row(BaseModel):
    id: int
    slug: str
    title: str
    brand: str
    status: str
    variant_count: int
    image_count: int
    translations: list[translation_state]


class admin_product_list_response(BaseModel):
    items: list[admin_product_row]
    page: int
    page_size: int
    total: int


class admin_category_row(BaseModel):
    """One choice in the product form's category picker.

    ``parent_name`` because "Sandals" is meaningless on its own and two parents
    may each have one; ``is_active`` because an inactive category is shown and
    marked rather than hidden.
    """

    id: int
    name: str
    slug: str
    parent_id: int
    parent_name: str
    position: int
    is_active: bool


class admin_product_create(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255)
    brand: str = Field(default="Pixi", max_length=128)
    category_id: int
    description: str | None = None
    tags: list[str] = []
    condition: ProductCondition = ProductCondition.new
    gender: Gender | None = None
    age_group: AgeGroup | None = None
    # products.item_group_id is String(64), and the SKU generated from it is
    # String(64) as well -- a long group id plus a long colour overflows the SKU.
    item_group_id: str | None = Field(default=None, max_length=64)


class admin_product_detail(BaseModel):
    id: int
    item_group_id: str
    slug: str
    title: str
    brand: str
    status: str
    category_id: int


class admin_translation_upsert(BaseModel):
    title: str | None = None
    description: str | None = None
    slug: str | None = None
    seo_title: str | None = None
    meta_description: str | None = None
    og_title: str | None = None
    og_description: str | None = None
    og_image_url: str | None = None
    image_alt: str | None = None
    is_published: bool | None = None


class admin_translation_detail(BaseModel):
    locale: str
    title: str | None
    description: str | None
    slug: str
    meta_description: str | None
    # Optional so the upsert and publish routes, which return an ORM row rather
    # than the editor's dict, keep validating against this same model.
    seo_title: str | None = None
    og_title: str | None = None
    og_description: str | None = None
    og_image_url: str | None = None
    image_alt: str | None = None
    is_published: bool
    is_complete: bool


class admin_variant_matrix(BaseModel):
    sizes: list[str] = Field(min_length=1)
    colors: list[str] = Field(min_length=1)
    price: Decimal = Field(ge=0)
    sale_price: Decimal | None = Field(default=None, ge=0)
    stock_quantity: int = Field(default=0, ge=0)
    availability: str = "in_stock"
    size_system: str | None = None
    material: str | None = None


class admin_blocker(BaseModel):
    code: str
    message: str


class admin_variant_row(BaseModel):
    id: int
    updated_at: datetime | None = None
    sku: str
    variant_title: str
    size: str | None
    color: str | None
    price: Decimal
    sale_price: Decimal | None
    stock_quantity: int
    is_active: bool


class admin_product_update(BaseModel):
    title: str | None = None
    slug: str | None = None
    brand: str | None = None
    category_id: int | None = None
    description: str | None = None
    tags: list[str] | None = None
    condition: ProductCondition | None = None
    gender: Gender | None = None
    age_group: AgeGroup | None = None
    # The row version this edit was built from. Optional: omitting it keeps
    # the previous last-write-wins behaviour, which is what every caller
    # written before this field did. See services/optimistic_lock.py.
    expected_updated_at: datetime | None = None


class admin_variant_update(BaseModel):
    # sku is here so the repository's refusal actually fires -- without this
    # field Pydantic silently drops an "sku" key before update_variant ever
    # sees it, so a caller attempting to change it got 200 OK and a no-op.
    sku: str | None = None
    variant_title: str | None = None
    price: Decimal | None = None
    sale_price: Decimal | None = None
    cost: Decimal | None = None
    stock_quantity: int | None = None
    availability: str | None = None
    gtin: str | None = None
    mpn: str | None = None
    material: str | None = None
    size_system: str | None = None
    weight_grams: int | None = None
    length_cm: Decimal | None = None
    width_cm: Decimal | None = None
    height_cm: Decimal | None = None
    merchant_eligible: bool | None = None
    is_active: bool | None = None
    # The row version this edit was built from. Optional: omitting it keeps
    # the previous last-write-wins behaviour, which is what every caller
    # written before this field did. See services/optimistic_lock.py.
    expected_updated_at: datetime | None = None


class admin_promotion_target(BaseModel):
    """``all`` covers the catalogue and takes no id; everything else needs one."""

    target_type: PromotionTargetType
    target_id: int | None = None


class admin_promotion_target_row(admin_promotion_target):
    id: int


class admin_promotion_create(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    type: PromotionType
    discount_percent: Decimal | None = Field(default=None, gt=0, le=100)
    discount_amount: Decimal | None = Field(default=None, gt=0)
    buy_quantity: int | None = Field(default=None, gt=0)
    get_quantity: int | None = Field(default=None, gt=0)
    get_discount_percent: Decimal | None = Field(default=None, gt=0, le=100)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    is_active: bool = True
    # Required at the boundary too: a promotion with no targets discounts
    # nothing, and saving one is never what the operator meant.
    targets: list[admin_promotion_target] = Field(min_length=1)


class admin_promotion_update(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    discount_percent: Decimal | None = Field(default=None, gt=0, le=100)
    discount_amount: Decimal | None = Field(default=None, gt=0)
    buy_quantity: int | None = Field(default=None, gt=0)
    get_quantity: int | None = Field(default=None, gt=0)
    get_discount_percent: Decimal | None = Field(default=None, gt=0, le=100)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    is_active: bool | None = None
    targets: list[admin_promotion_target] | None = None


class admin_promotion_row(BaseModel):
    id: int
    name: str
    type: str
    discount_percent: Decimal | None = None
    discount_amount: Decimal | None = None
    buy_quantity: int | None = None
    get_quantity: int | None = None
    get_discount_percent: Decimal | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    is_active: bool
    targets: list[admin_promotion_target_row] = []


class admin_image_row(BaseModel):
    id: int
    url: str
    alt_text: str
    width: int
    height: int
    is_primary: bool
    position: int
    variant_id: int | None = None


class admin_image_order(BaseModel):
    """The whole set, in the order it should hold.

    Every image exactly once: uq_product_images_position is not deferrable, so a
    partial list leaves the omitted rows holding positions the new ones collide
    with.
    """

    image_ids: list[int] = Field(min_length=1)
    variant_id: int | None = None


class admin_image_alt_upsert(BaseModel):
    alt_text: str = Field(min_length=1, max_length=500)
    title_attr: str | None = None


class admin_image_translation_detail(BaseModel):
    locale: str
    alt_text: str
    title_attr: str | None = None


class admin_product_full(BaseModel):
    id: int
    updated_at: datetime | None = None
    item_group_id: str
    slug: str
    title: str
    brand: str
    status: str
    category_id: int
    # Everything the editor is allowed to change. Reading back exactly the set
    # admin_product_update writes is what keeps the form from showing blank for
    # a value that exists.
    description: str | None = None
    condition: str | None = None
    gender: str | None = None
    age_group: str | None = None
    tags: list[str] = []
    translations: list[admin_translation_detail]
    variants: list[admin_variant_row]
    images: list[admin_image_row] = []
