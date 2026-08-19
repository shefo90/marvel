"""Admin catalog contracts. No logic here — see repositories/admin_catalog.py.

The enum-typed fields are typed against ``core.enums`` rather than ``str``
deliberately. Those columns are ``SAEnum(native_enum=False)`` with no CHECK
behind them, so an unknown value is *written* happily and then raises
LookupError on every subsequent read of the row — the product becomes
unloadable. Rejecting it at the boundary is the only place that costs nothing.
"""

from decimal import Decimal

from pydantic import BaseModel, Field

from core.enums import AgeGroup, Gender, ProductCondition


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


class admin_product_full(BaseModel):
    id: int
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
