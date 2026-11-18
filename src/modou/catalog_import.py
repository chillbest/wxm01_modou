"""0010 catalog writes, shared by CLI and HTTP review."""
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from .models import GameProductConfig, GameAlias
from .observations import get_or_create_source


def import_catalog_0010(conn, rows, *, allow_updates=False, source_id=None):
    if conn.dialect.name == 'postgresql':
        conn.execute(text('LOCK TABLE data_source, game_product_config, game_alias IN SHARE ROW EXCLUSIVE MODE'))
    ids = []
    sources = {}
    with Session(bind=conn, expire_on_commit=False) as session:
        for row in rows:
            if row['status'] != 'confirmed':
                continue
            from .blacklist import is_blacklisted
            if is_blacklisted(row):
                raise ValueError('黑名单条目不可入库')
            final = row['final']
            quote = row.get('quote') or {}
            source = None
            def row_source_id():
                nonlocal source
                if source_id is not None:
                    return source_id
                if source is None:
                    key = (quote.get('source_path'), quote.get('published_at'))
                    if key not in sources:
                        sources[key] = get_or_create_source(session, *key)
                    source = sources[key]
                return source.sources_id
            platform = (row.get('quote') or {}).get('platform') or final.get('platform')
            if not isinstance(platform, str) or not platform.strip():
                raise ValueError('GPC平台必填')
            product = session.get(GameProductConfig, final['gpc_id']) if final.get('gpc_id') else None
            if final.get('gpc_id') and product is None:
                raise ValueError('已有GPC不存在')
            sid, link = final.get('bangumi_id'), final.get('outlink')
            if product is not None:
                sid = final.get('bangumi_id', product.bangumi_id)
                link = final.get('outlink', product.outlink)
                if product.platform != platform or product.bangumi_id != sid or product.outlink != link:
                    raise ValueError('GPC身份已改变，请取消勾选后点击“重新加载此GPC”，核对最新资料后入库')
            else:
                matches = session.scalars(select(GameProductConfig).where(
                    GameProductConfig.bangumi_id == sid, GameProductConfig.platform == platform,
                    GameProductConfig.outlink == link)).all()
                if len(matches) > 1:
                    raise ValueError('存在多个相同身份GPC，请指定gpc_id')
                product = matches[0] if matches else None
            main = final.get('bangumi_main', product.bangumi_main if product is not None else None)
            fields = {k: final.get(k, getattr(product, k) if product is not None else None) for k in ('name_zh', 'name_en', 'type', 'note', 'display_name')}
            from .main_ids import normalize_main
            fields['bangumi_main'] = normalize_main(main)
            if product is None:
                product = GameProductConfig(**fields, bangumi_id=sid, outlink=link, platform=platform, sources_id=row_source_id())
                session.add(product)
                session.flush()
            elif allow_updates:
                if not final.get('gpc_id') and any(getattr(product, k) != value for k, value in fields.items()):
                    raise ValueError('同身份GPC已存在且资料不同，请重新粘贴产品URL加载本地资料')
                baseline = row.get('gpc_baseline')
                if baseline is not None and any(getattr(product, k) != baseline.get(k) for k in fields) and any(getattr(product, k) != value for k, value in fields.items()):
                    raise ValueError('GPC已被其他审核修改，请重新加载')
                for key, value in fields.items():
                    setattr(product, key, value)
                session.flush()
            else:
                for key, value in fields.items():
                    if key in final and getattr(product, key) != value:
                        raise ValueError('已有GPC资料冲突')
            if session.scalar(select(GameAlias).where(GameAlias.gpc_id == product.gpc_id, GameAlias.alias == row['raw_name'])) is None:
                session.add(GameAlias(gpc_id=product.gpc_id, alias=row['raw_name'], sources_id=row_source_id()))
            ids.append(product.gpc_id)
        session.flush()
    return ids
