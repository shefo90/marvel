"""Parent product — section 2's ``product_id`` and section 3's ``parent_product_id``.

Holds everything true of the whole variant family. Carries no price and no
stock: those live only on the sellable variant, which is the single source of
truth for section 8's price/availability contract.
"""

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Enum as SAEnum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from core.enums import AgeGroup, Gender, ProductCondition, ProductStatus
from models.mixins import SeoMixin, TimestampMixin


class Product(Base, TimestampMixin, SeoMixin):
    __tablename__ = "products"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Section 8: groups variants for ProductGroup structured data and the feed.
    item_group_id = mapped_column(String(64), nullable=False)
    slug = mapped_column(String(180), nullable=False)
    title = mapped_column(String(255), nullable=False)
    description = mapped_column(Text, nullable=True)
    # Single house brand (spec section 2 "Decisions locked"). Defaulted from
    # HOUSE_BRAND rather than given its own table.
    brand = mapped_column(String(120), nullable=False)

    category_id = mapped_column(BigInteger, nullable=False)
    # Open question 12: products attach to level-2 categories only. Generated so
    # the composite FK below cannot be satisfied by a level-1 category.
    category_level = mapped_column(
        SmallInteger, Computed("2", persisted=True), nullable=False
    )

    product_type = mapped_column(String(255), nullable=True)
    tags = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    condition = mapped_column(
        SAEnum(ProductCondition, native_enum=False, length=16),
        nullable=False,
        server_default=ProductCondition.new.value,
    )
    gender = mapped_column(
        SAEnum(Gender, native_enum=False, length=16),
        nullable=True,
        server_default=Gender.female.value,
    )
    age_group = mapped_column(
        SAEnum(AgeGroup, native_enum=False, length=16), nullable=True
    )
    status = mapped_column(
        SAEnum(ProductStatus, native_enum=False, length=16),
        nullable=False,
        server_default=ProductStatus.draft.value,
    )
    default_variant_id = mapped_column(BigInteger, nullable=True)

    category = relationship(
        "Category",
        back_populates="products",
        foreign_keys="[Product.category_id, Product.category_level]",
    )
    variants = relationship(
        "ProductVariant",
        back_populates="product",
        foreign_keys="ProductVariant.product_id",
        order_by="ProductVariant.id",
    )
    # Read-only convenience join. The composite FK below is what enforces that
    # the chosen variant actually belongs to this product; this relationship
    # just resolves it for rendering.
    default_variant = relationship(
        "ProductVariant",
        primaryjoin="Product.default_variant_id == ProductVariant.id",
        foreign_keys="[Product.default_variant_id]",
        uselist=False,
        viewonly=True,
    )
    images = relationship(
        "ProductImage",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductImage.position",
    )
    collection_links = relationship(
        "CollectionProduct", back_populates="product", cascade="all, delete-orphan"
    )
    translations = relationship(
        "ProductTranslation", back_populates="product", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("slug", name="uq_products_slug"),
        UniqueConstraint("item_group_id", name="uq_products_item_group_id"),
        # Composite FK target for the default-variant guard below.
        UniqueConstraint("id", "default_variant_id", name="uq_products_id_default_variant"),
        ForeignKeyConstraint(
            ["category_id", "category_level"],
            ["categories.id", "categories.level"],
            name="fk_products_category",
            ondelete="RESTRICT",
        ),
        # Structurally forbids pointing default_variant_id at another product's
        # variant. use_alter breaks the products <-> product_variants cycle.
        ForeignKeyConstraint(
            ["id", "default_variant_id"],
            ["product_variants.product_id", "product_variants.id"],
            name="fk_products_default_variant",
            ondelete="SET NULL",
            use_alter=True,
        ),
        CheckConstraint(
            r"slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="ck_products_slug_format"
        ),
        CheckConstraint(
            "status <> 'active' OR default_variant_id IS NOT NULL",
            name="ck_products_active_has_default_variant",
        ),
        Index("ix_products_category_id", "category_id"),
        Index("ix_products_status", "status"),
        Index("ix_products_item_group_id", "item_group_id"),
        Index("ix_products_tags", "tags", postgresql_using="gin"),
        # Section 8A: sitemap membership and lastmod.
        Index(
            "ix_products_sitemap",
            "content_updated_at",
            postgresql_where=text("status = 'active' AND is_indexable"),
        ),
    )
