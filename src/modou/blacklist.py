"""Reserved alias target; a blacklist entry never represents a product or quote."""
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from .models import GameProductConfig, GameAlias
from .observations import get_or_create_source

BLACKLIST_ID = -1
BLACKLIST_NAME = '【黑名单占位】'


def is_blacklisted(row):
    return bool(row.get('blacklisted') or str((row.get('final') or {}).get('gpc_id')) == '-1')


def mark_blacklisted(row):
    row.update(blacklisted=True, already_imported=True, selected=False)
    row.setdefault('final', {})['gpc_id'] = BLACKLIST_ID
    row.pop('candidate_lookup', None)


def ensure_sentinel(conn):
    if conn.dialect.name == 'postgresql':
        conn.execute(text('LOCK TABLE data_source, game_product_config, game_alias IN SHARE ROW EXCLUSIVE MODE'))
    with Session(bind=conn) as session:
        product = session.get(GameProductConfig, BLACKLIST_ID)
        if product is not None:
            if product.name_zh != BLACKLIST_NAME or product.platform != 'blacklist':
                raise ValueError('gpc_id=-1已被其他记录占用')
            return
        source = get_or_create_source(session, '系统：黑名单占位')
        session.add(GameProductConfig(gpc_id=BLACKLIST_ID, name_zh=BLACKLIST_NAME,
                                     platform='blacklist', sources_id=source.sources_id))
        session.flush()


def add_alias(conn, value, batch):
    from .bangumi import normalized
    value = value.strip()
    if not value:
        raise ValueError('黑名单文本不能为空')
    ensure_sentinel(conn)
    with Session(bind=conn) as session:
        aliases = session.scalars(select(GameAlias.alias).where(GameAlias.gpc_id == BLACKLIST_ID)).all()
        if any(normalized(alias) == normalized(value) for alias in aliases):
            return
        source = get_or_create_source(session, batch['source_path'], review_batch_id=batch['id'],
                                      recorded_at=batch['created_at'])
        session.add(GameAlias(gpc_id=BLACKLIST_ID, alias=value, sources_id=source.sources_id))
        session.flush()
