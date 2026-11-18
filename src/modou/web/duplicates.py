"""Database identity checks used by draft refresh and transactional commit."""
import hashlib
import json
from sqlalchemy import select
from ..models import GameProductConfig, PriceRecord
from ..web_review import eligibility_errors


class SimilarProducts(ValueError):
    def __init__(self, conflicts):
        super().__init__('game_product_config表内已经存在相似数据，是否还要插入。')
        self.conflicts = conflicts


def product_matches(conn, row):
    f, q = row['final'], row['quote']
    table = GameProductConfig.__table__
    if f.get('gpc_id'):
        records = conn.execute(select(table).where(table.c.gpc_id == f['gpc_id'], table.c.gpc_id != -1)).mappings().all()
        return [r for r in records if r['bangumi_id'] == f.get('bangumi_id')
                and r['platform'] == q.get('platform') and r['outlink'] == f.get('outlink')]
    return conn.execute(select(table).where(table.c.bangumi_id == f.get('bangumi_id'),
        table.c.platform == q.get('platform'), table.c.outlink == f.get('outlink'))).mappings().all()


def existing_quote(conn, row, *, require_complete=True):
    if require_complete and eligibility_errors(row):
        return None
    products = product_matches(conn, row)
    if len(products) != 1:
        return None
    from ..note_review import ApprovedQuote
    quote = ApprovedQuote.model_validate(row['quote'])
    table = PriceRecord.__table__
    record = conn.execute(select(table.c.record_id).where(
        table.c.gpc_id == products[0]['gpc_id'], table.c.region == quote.region,
        table.c.lowprice_cny == quote.lowprice_cny, table.c.lowprice_method == quote.lowprice_method,
        table.c.lowprice_date == quote.lowprice_date).order_by(table.c.record_id)).first()
    return {'gpc_id': products[0]['gpc_id'], 'record_id': record[0]} if record else None


def similar_products(conn, rows):
    conflicts = []
    table = GameProductConfig.__table__
    for index, row in enumerate(rows):
        f, q = row['final'], row['quote']
        # Missing IDs do not establish similarity between unrelated products.
        if not str(f.get('bangumi_id') or '').strip():
            continue
        if f.get('gpc_id') or product_matches(conn, row) or existing_quote(conn, row):
            continue
        records = conn.execute(select(table).where(table.c.bangumi_id == f.get('bangumi_id'),
            table.c.platform == q.get('platform')).order_by(table.c.gpc_id)).mappings().all()
        if not records:
            continue
        snapshot = json.dumps({'final': f, 'quote': q, 'existing': [dict(r) for r in records]},
                              ensure_ascii=False, sort_keys=True, default=str)
        conflicts.append({'index': index, 'token': hashlib.sha256(snapshot.encode()).hexdigest(),
                          'existing': [{k: r[k] for k in ('gpc_id', 'name_zh', 'bangumi_id', 'platform', 'outlink')} for r in records]})
    return conflicts


def mark_duplicates(conn, batch):
    from ..blacklist import is_blacklisted, mark_blacklisted
    from ..bangumi import normalized
    from ..models import GameAlias
    blocked = {normalized(value) for value in conn.scalars(select(GameAlias.alias).where(GameAlias.gpc_id == -1))}
    for row in batch['rows']:
        if row.get('imported'):
            continue
        if is_blacklisted(row) or normalized(row.get('raw_name') or '') in blocked:
            mark_blacklisted(row)
            continue
        receipt = existing_quote(conn, row)
        if receipt:
            row.update(already_imported=True, selected=True, receipt=receipt)
        elif row.pop('already_imported', False):
            row.update(selected=False)
            row.pop('receipt', None)
