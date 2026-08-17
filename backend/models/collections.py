"""Curated merchandising collections — "Summer Edit", "Pixi Comfort", "Office Edit".

These cut *across* the category tree. ``list_id`` is section 5's
``item_list_id``, which is why the same identifier must reach the dataLayer, the
cart line and the order line unchanged.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from models.mixins import SeoMixin, TimestampMixin


class Collection(Base, TimestampMixin, SeoMixin):
    __tablename__ = "collections"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    list_id = mapped_column(String(64), nullable=False)
    name = mapped_column(String(120), nullable=False)
    slug = mapped_column(String(160), nullable=False)
    description = mapped_column(Text, nullable=True)
    position = mapped_column(SmallInteger, nullable=False, server_default="0")
    is_active = mapped_column(Boolean, nullable=False, server_default="true")

    product_links = relationship(
        "CollectionProduct",
        back_populates="collection",
        cascade="all, delete-orphan",
        order_by="CollectionProduct.position",
    )
    translations = relationship(
        "CollectionTranslation", back_populates="collection", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("slug", name="uq_collections_slug"),
        UniqueConstraint("list_id", name="uq_collections_list_id"),
        CheckConstraint(
            r"slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="ck_collections_slug_format"
        ),
        CheckConstraint(
            r"list_id ~ '^[a-z0-9_]+$'", name="ck_collections_list_id_format"
        ),
        Index("ix_collections_active", "position", postgresql_where=text("is_active")),
        Index(
            "ix_collections_sitemap",
            "content_updated_at",
            postgresql_where=text("is_active AND is_indexable"),
        ),
    )
