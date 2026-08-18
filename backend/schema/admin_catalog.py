"""Admin catalog contracts. No logic here — see repositories/admin_catalog.py."""

from decimal import Decimal

from pydantic import BaseModel, Field


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


class admin_product_create(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255)
    brand: str = Field(default="Pixi", max_length=128)
    category_id: int
    description: str | None = None
    tags: list[str] = []
    condition: str = "new"
    gender: str | None = None
    age_group: str | None = None
    item_group_id: str | None = None


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
    is_published: bool
    is_complete: bool


class admin_variant_matrix(BaseModel):
    sizes: list[str] = Field(min_length=1)
    colors: list[str] = Field(min_length=1)
    price: Decimal
    sale_price: Decimal | None = None
    stock_quantity: int = 0
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
    condition: str | None = None
    gender: str | None = None
    age_group: str | None = None


class admin_variant_update(BaseModel):
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
    translations: list[admin_translation_detail]
    variants: list[admin_variant_row]
