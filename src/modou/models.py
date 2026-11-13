from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint,
                        Index, Numeric, Text, UniqueConstraint, BigInteger, Integer, func, text)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


ID = BigInteger().with_variant(Integer, "sqlite")


class GameName(Base):
    __tablename__ = "game_name"
    name_id: Mapped[int] = mapped_column(ID, primary_key=True)
    name_zh: Mapped[str] = mapped_column(Text, index=True)
    name_en: Mapped[str | None] = mapped_column(Text, index=True)


class GameVariant(Base):
    __tablename__ = "game_variant"
    __table_args__ = (
        UniqueConstraint("name_id", "platform", "edition", name="uq_variant_spec"),
        UniqueConstraint("variant_id", "name_id", name="uq_variant_owner"),
        CheckConstraint("platform IN ('PS5', 'PS4')", name="ck_platform"),
    )
    variant_id: Mapped[int] = mapped_column(ID, primary_key=True)
    name_id: Mapped[int] = mapped_column(ForeignKey("game_name.name_id"))
    platform: Mapped[str] = mapped_column(Text)
    edition: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    remark: Mapped[str | None] = mapped_column(Text)


class GameAlias(Base):
    __tablename__ = "game_alias"
    __table_args__ = (
        ForeignKeyConstraint(["variant_id", "name_id"], ["game_variant.variant_id", "game_variant.name_id"], name="fk_alias_variant_owner"),
        Index("ix_alias", "alias"),
        Index("uq_alias_game", "name_id", "alias", unique=True,
              postgresql_where=text("variant_id IS NULL"), sqlite_where=text("variant_id IS NULL")),
        Index("uq_alias_variant", "name_id", "variant_id", "alias", unique=True,
              postgresql_where=text("variant_id IS NOT NULL"), sqlite_where=text("variant_id IS NOT NULL")),
    )
    alias_id: Mapped[int] = mapped_column(ID, primary_key=True)
    name_id: Mapped[int] = mapped_column(ForeignKey("game_name.name_id"))
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("game_variant.variant_id"))
    alias: Mapped[str] = mapped_column(Text)


class DataSource(Base):
    __tablename__ = "data_source"
    sources_id: Mapped[int] = mapped_column(ID, primary_key=True)
    source_url: Mapped[str] = mapped_column(Text, unique=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PriceRecord(Base):
    __tablename__ = "m_low_record"
    __table_args__ = (
        CheckConstraint("lowprice_cny > 0", name="ck_positive_price"),
        Index("ix_price_lookup", "variant_id", "region", "lowprice_cny", "lowprice_date"),
        Index("ix_price_source", "sources_id"),
    )
    record_id: Mapped[int] = mapped_column(ID, primary_key=True)
    variant_id: Mapped[int] = mapped_column(ForeignKey("game_variant.variant_id"))
    sources_id: Mapped[int] = mapped_column(ForeignKey("data_source.sources_id"))
    region: Mapped[str] = mapped_column(Text)
    lowprice_cny: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    lowprice_method: Mapped[str] = mapped_column(Text)
    lowprice_date: Mapped[date] = mapped_column(Date)
