from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from .models import DataSource, GameAlias, GameName as N, GameVariant as V, PriceRecord as R


def search_games(session: Session, keyword: str):
    """按名称/别名字面匹配；规格别名仅命中该规格对应的平台。"""
    keyword = keyword.strip()
    if not keyword:
        return []
    alias_hit = select(GameAlias.alias_id).where(
        GameAlias.name_id == N.name_id,
        or_(GameAlias.variant_id.is_(None), GameAlias.variant_id == V.variant_id),
        GameAlias.alias.icontains(keyword, autoescape=True),
    ).correlate(N, V).exists()
    query = select(N.name_zh, V.platform).join(V, V.name_id == N.name_id).where(or_(
        N.name_zh.icontains(keyword, autoescape=True),
        N.name_en.icontains(keyword, autoescape=True), alias_hit,
    )).distinct().order_by(N.name_zh, V.platform)
    return session.execute(query).all()


def lowest_prices(session: Session, name_zh: str, platform: str, edition: str):
    """只读：各地区组最低价，同价取日期、ID较大者。"""
    group = case((R.region == "国行", "国行版"), (R.region.in_(["港版", "台版"]), "港版"), else_="海外版")
    ranked = select(R.record_id.label("observation_id"), group.label("region_group"), func.row_number().over(
        partition_by=group, order_by=(R.lowprice_cny.asc(), R.lowprice_date.desc(), R.record_id.desc())
    ).label("position")).join(V, V.variant_id == R.variant_id).join(N, N.name_id == V.name_id).where(
        N.name_zh == name_zh, V.platform == platform, V.edition == edition).subquery()
    query = select(R, ranked.c.region_group, DataSource.source_url, DataSource.recorded_at).join(
        ranked, ranked.c.observation_id == R.record_id
    ).join(DataSource, DataSource.sources_id == R.sources_id).where(ranked.c.position == 1).order_by(
        case((ranked.c.region_group == "国行版", 0), (ranked.c.region_group == "港版", 1), else_=2)
    )
    return session.execute(query).all()
