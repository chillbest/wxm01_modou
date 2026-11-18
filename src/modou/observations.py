"""已校验报价的持久化原语；审批、URL归一及整批提交由M03负责。"""
from datetime import date, datetime, timezone
import re
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .models import DataSource, PriceRecord, GameProductConfig


def save_observation(session: Session, *, source_path: str, gpc_id: int, platform: str,
                     region: str, lowprice_cny, lowprice_date, lowprice_method: str,
                     published_at=None, source_id=None) -> PriceRecord:
    """跨来源同报价复用；仅实际新增时创建本次提交的来源。"""
    if session.bind.dialect.name == "postgresql":
        session.execute(text("LOCK TABLE data_source, m_low_record IN SHARE ROW EXCLUSIVE MODE"))
    if str(gpc_id) == '-1':
        raise ValueError('黑名单条目不可写入报价')
    product = session.get(GameProductConfig, gpc_id)
    if product is None or product.platform != platform:
        raise ValueError('报价平台与GPC不一致')
    fields = dict(gpc_id=gpc_id, region=region,
                  lowprice_cny=lowprice_cny, lowprice_date=lowprice_date, lowprice_method='直接购买' if lowprice_method == '' else lowprice_method)
    existing = session.scalar(select(PriceRecord).where(
        *(getattr(PriceRecord, key) == value for key, value in fields.items())))
    if existing is not None:
        return existing
    if source_id is None:
        source_id = get_or_create_source(session, source_path, published_at).sources_id
    record = PriceRecord(**fields, sources_id=source_id)
    session.add(record)
    session.flush()
    return record


def get_or_create_source(session: Session, source_path=None, published_at=None, *,
                         review_batch_id=None, recorded_at=None) -> DataSource:
    """Reuse only an explicit review batch; never infer identity from time."""
    if not source_path:
        source_path = '手动插入'
    if not isinstance(source_path, str) or not source_path.strip():
        raise ValueError('来源必须为非空文字')
    if isinstance(published_at, str):
        published_at = date.fromisoformat(published_at)
    if session.bind.dialect.name == 'postgresql':
        session.execute(text('LOCK TABLE data_source IN SHARE ROW EXCLUSIVE MODE'))
    if review_batch_id is not None:
        if not isinstance(review_batch_id, str) or not re.fullmatch(r'(?:[a-f0-9]{8}|[a-f0-9]{32})', review_batch_id):
            raise ValueError('审核批次标识无效')
        if isinstance(recorded_at, str):
            recorded_at = datetime.fromisoformat(recorded_at)
        if not isinstance(recorded_at, datetime) or recorded_at.tzinfo is None:
            raise ValueError('审核批次创建时间缺失或无时区，不能推测生成时间')
    source = (session.scalar(select(DataSource).where(DataSource.review_batch_id == review_batch_id))
              if review_batch_id is not None else None)
    if source is None:
        source = DataSource(source_path=source_path, published_at=published_at,
                            review_batch_id=review_batch_id,
                            recorded_at=recorded_at or datetime.now(timezone.utc))
        session.add(source)
        session.flush()
    if source.source_path != source_path:
        raise ValueError('同一审核批次的来源路径冲突')
    if source.published_at != published_at and published_at is not None:
        raise ValueError('同一来源的发布日期冲突，请核实日期')
    return source
