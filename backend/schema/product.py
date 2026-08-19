"""Catalog read contracts.

Zero logic — Pydantic models only.

Note which identifiers appear here. ``sku`` is section 2's sellable identifier,
and it is the same string the dataLayer sends as ``item_id``, the Merchant feed
sends as ``offer_id`` and the Meta catalog sends as ``content_id``. The response
deliberately exposes it under its own name rather than renaming it per consumer,
so no client is tempted to invent a second identity.

Localized text comes from the translation row; price, stock and SKU come from
the base variant row and are never localized (section 8's single-source rule).
"""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class image_response(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    url: str
    alt_text: str
    width: int
    height: int
    is_primary: bool
    position: int


class variant_response(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    # Section 2: the sellable identifier. Same value as GA4/Ads item_id.
    sku: str
    variant_title: str
    size: str | None = None
    size_system: str | None = None
    color: str | None = None
    material: str | None = None
    price: Decimal
    sale_price: Decimal | None = None
    currency: str
    availability: str
    stock_quantity: int
    gtin: str | None = None


class attribute_option(BaseModel):
    """A colour or size, by canonical code and localized label.

    ``code`` is what a variant stores and what a filter sends back; ``label`` is
    display text and differs per locale. Filtering on the label would break the
    moment the Arabic page sent "أسود" where the column holds "black".
    """

    code: str
    label: str


class facet_option(attribute_option):
    count: int
    selected: bool = False


class price_bounds(BaseModel):
    min: Decimal | None = None
    max: Decimal | None = None


class listing_facets(BaseModel):
    """What the shopper can still narrow by, and how much each would leave.

    Counts exclude their own facet, so ticking one size does not zero every
    other size -- those are precisely the boxes that would widen the result.
    """

    sizes: list[facet_option] = []
    colors: list[facet_option] = []
    price: price_bounds = price_bounds()


class product_summary(BaseModel):
    """Card shape for listings. Carries the list identity so the frontend can
    emit section 5's ``view_item_list`` / ``select_item`` without a second call."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    title: str
    brand: str
    item_group_id: str
    # GA4/Ads item_id for this row -- the cheapest active variant, whose price
    # the row shows. None only when the product has no sellable variant.
    sku: str | None = None
    price: Decimal | None = None
    sale_price: Decimal | None = None
    currency: str = "EGP"
    primary_image: image_response | None = None
    # The second photograph, for the card's hover swap. None when the product
    # has only one, so the frontend need not guess whether a swap exists.
    hover_image: image_response | None = None
    colors: list[attribute_option] = []
    # In-stock sizes only: a size shown on a card is an implicit promise it can
    # be bought.
    sizes: list[attribute_option] = []
    item_list_id: str | None = None
    item_list_name: str | None = None
    index: int | None = None


class product_response(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    locale: str
    title: str
    description: str | None = None
    brand: str
    item_group_id: str
    category_slug: str | None = None
    category_name: str | None = None
    product_type: str | None = None
    condition: str
    tags: list[str] = []

    # Section 8A: emitted into the initial server-rendered HTML by S2.
    seo_title: str | None = None
    meta_description: str | None = None
    is_indexable: bool = True
    canonical_url: str | None = None
    og_title: str | None = None
    og_description: str | None = None
    og_image_url: str | None = None
    # Locale -> URL, for the reciprocal hreflang cluster. Empty when this
    # product is published in one locale only, which is deliberate: a cluster
    # of size one emits no hreflang at all.
    alternates: dict[str, str] = {}

    images: list[image_response] = []
    variants: list[variant_response] = []
    default_variant_sku: str | None = None


class product_list_response(BaseModel):
    items: list[product_summary]
    total: int
    page: int
    page_size: int
    item_list_id: str | None = None
    item_list_name: str | None = None
    sort: str = "featured"
    facets: listing_facets = listing_facets()
