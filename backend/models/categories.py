"""Two-level merchandising taxonomy.

Level 1: Shoes, Bags. Level 2: flats/sandals/heels/sneakers/boots/espadrilles,
handbags/crossbody/clutches/wallets/backpacks.

The two-level shape is enforced structurally rather than by convention: a
composite self-FK plus a generated ``parent_level`` column makes a three-level
tree unrepresentable.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
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
from models.mixins import SeoMixin, TimestampMixin


class Category(Base, TimestampMixin, SeoMixin):
    __tablename__ = "categories"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    parent_id = mapped_column(BigInteger, nullable=True)
    level = mapped_column(SmallInteger, nullable=False)
    # A level-2 category's parent must be level 1. Generating the value removes
    # any way for application code to get it wrong.
    parent_level = mapped_column(
        SmallInteger,
        Computed("CASE WHEN parent_id IS NULL THEN NULL ELSE 1 END", persisted=True),
        nullable=True,
    )
    name = mapped_column(String(120), nullable=False)
    slug = mapped_column(String(160), nullable=False)
    # Section 5's item_list_id when a category listing renders.
    list_id = mapped_column(String(64), nullable=False)
    description = mapped_column(Text, nullable=True)
    google_product_category = mapped_column(String(255), nullable=True)
    position = mapped_column(SmallInteger, nullable=False, server_default="0")
    is_active = mapped_column(Boolean, nullable=False, server_default="true")

    parent = relationship(
        "Category", back_populates="children", remote_side=[id], foreign_keys=[parent_id]
    )
    children = relationship("Category", back_populates="parent")
    products = relationship("Product", back_populates="category")
    translations = relationship(
        "CategoryTranslation", back_populates="category", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("slug", name="uq_categories_slug"),
        UniqueConstraint("list_id", name="uq_categories_list_id"),
        # Composite FK targets — referenced by the self-FK and by products.
        UniqueConstraint("id", "level", name="uq_categories_id_level"),
        ForeignKeyConstraint(
            ["parent_id", "parent_level"],
            ["categories.id", "categories.level"],
            name="fk_categories_parent",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(level = 1 AND parent_id IS NULL) OR (level = 2 AND parent_id IS NOT NULL)",
            name="ck_categories_two_levels",
        ),
        CheckConstraint("level IN (1, 2)", name="ck_categories_level_range"),
        CheckConstraint(
            r"slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="ck_categories_slug_format"
        ),
        Index("ix_categories_parent_id", "parent_id"),
        Index(
            "ix_categories_active_nav",
            "level",
            "position",
            postgresql_where=text("is_active"),
        ),
    )
