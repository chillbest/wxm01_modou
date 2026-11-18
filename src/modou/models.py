from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint,
                        Index, Numeric, Text, UniqueConstraint, BigInteger, Integer, func, text)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


ID = BigInteger().with_variant(Integer, "sqlite")


GPC_TYPES = ("Base", "rebase", "Expansion", "母子集", "合集")


class GameProductConfig(Base):
    __tablename__ = "game_product_config"
    __table_args__ = (UniqueConstraint("bangumi_id", "platform", "outlink", name="uq_gpc_bangumi_platform_outlink"),
                      Index("ix_gpc_name_zh", "name_zh"), Index("ix_gpc_name_en", "name_en"),
                      CheckConstraint("type IN ('Base', 'rebase', 'Expansion', '母子集', '合集')", name="ck_gpc_type"))
    gpc_id: Mapped[int] = mapped_column(ID, primary_key=True)
    name_zh: Mapped[str] = mapped_column(Text)
    name_en: Mapped[str | None] = mapped_column(Text)
    bangumi_id: Mapped[str | None] = mapped_column(Text)
    bangumi_main: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    outlink: Mapped[str | None] = mapped_column(Text, comment='游戏产品外链；完整HTTP/HTTPS URL，不限定网站')
    type: Mapped[str | None] = mapped_column(Text)
    platform: Mapped[str] = mapped_column(Text)
    sources_id: Mapped[int] = mapped_column(ForeignKey("data_source.sources_id"))


class GameAlias(Base):
    __tablename__ = "game_alias"
    __table_args__ = (UniqueConstraint("alias", name="uq_alias"), Index("ix_alias", "alias"))
    alias_id: Mapped[int] = mapped_column(ID, primary_key=True)
    gpc_id: Mapped[int] = mapped_column(ForeignKey("game_product_config.gpc_id"))
    alias: Mapped[str] = mapped_column(Text)
    sources_id: Mapped[int] = mapped_column(ForeignKey("data_source.sources_id"))


class DataSource(Base):
    __tablename__ = "data_source"
    __table_args__ = (UniqueConstraint('review_batch_id', name='uq_source_review_batch'),)
    sources_id: Mapped[int] = mapped_column(ID, primary_key=True)
    source_path: Mapped[str] = mapped_column(Text)
    published_at: Mapped[date | None] = mapped_column(Date)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment='审核批次创建时间；非审核来源为创建来源时间')
    review_batch_id: Mapped[str | None] = mapped_column(Text, comment='动态审核批次标识，兼容8位及历史32位')


class PriceRecord(Base):
    __tablename__ = "m_low_record"
    __table_args__ = (
        CheckConstraint("length(trim(lowprice_method)) > 0", name="ck_price_method_nonempty"),
        CheckConstraint("lowprice_cny > 0", name="ck_positive_price"),
        Index("ix_price_lookup", "gpc_id", "region", "lowprice_cny", "lowprice_date"),
        Index("ix_price_source", "sources_id"),
    )
    record_id: Mapped[int] = mapped_column(ID, primary_key=True)
    gpc_id: Mapped[int] = mapped_column(ForeignKey("game_product_config.gpc_id"))
    sources_id: Mapped[int] = mapped_column(ForeignKey("data_source.sources_id"))
    region: Mapped[str] = mapped_column(Text)
    lowprice_cny: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    lowprice_method: Mapped[str] = mapped_column(Text)
    lowprice_date: Mapped[date] = mapped_column(Date)
