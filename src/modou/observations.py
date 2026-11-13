"""已校验报价的持久化原语；审批、URL归一及整批提交由M03负责。"""
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .models import DataSource, PriceRecord


def save_observation(session: Session, *, source_url: str, variant_id: int,
                     region: str, lowprice_cny, lowprice_date, lowprice_method: str,
                     published_at=None) -> PriceRecord:
    """同来源同报价复用；一篇笔记共用来源，不覆盖旧报价或来源时间。"""
    if session.bind.dialect.name == "postgresql":
        session.execute(text("LOCK TABLE data_source, m_low_record IN SHARE ROW EXCLUSIVE MODE"))
    source = session.scalar(select(DataSource).where(DataSource.source_url == source_url))
    if source is None:
        source = DataSource(source_url=source_url, published_at=published_at)
        session.add(source)
        session.flush()
    fields = dict(variant_id=variant_id, sources_id=source.sources_id, region=region,
                  lowprice_cny=lowprice_cny, lowprice_date=lowprice_date, lowprice_method=lowprice_method)
    existing = session.scalar(select(PriceRecord).where(
        *(getattr(PriceRecord, key) == value for key, value in fields.items())))
    if existing is not None:
        return existing
    record = PriceRecord(**fields)
    session.add(record)
    session.flush()
    return record
