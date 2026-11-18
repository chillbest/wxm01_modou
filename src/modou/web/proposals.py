"""Read-only insert previews, using the same product/quote identity as commit."""
from sqlalchemy import select
from ..models import GameAlias, GameProductConfig, PriceRecord, GPC_TYPES
from .duplicates import product_matches, existing_quote


def proposed_inserts(conn, row):
    from ..blacklist import is_blacklisted
    if is_blacklisted(row):
        return []
    if row.get('imported') or row.get('already_imported'):
        return stored_records(conn, row)
    f, q = row['final'], row['quote']
    products = product_matches(conn, row)
    if len(products) > 1:
        return []  # Ambiguous identities must be resolved before insertion.
    product = products[0] if products else None
    gpc = product['gpc_id'] if product else '待生成：' + str(f.get('name_zh') or row['raw_name'])
    tables = []
    if product is None:
        fields = ('name_zh', 'name_en', 'bangumi_id', 'bangumi_main', 'note', 'display_name', 'outlink', 'type')
        data = {k: f.get(k) for k in fields}
        data['type'] = data['type'] if data['type'] in GPC_TYPES else None
        data = {k: v for k, v in data.items() if k not in ('note', 'display_name', 'outlink') or v not in (None, '')}
        data['platform'] = q.get('platform')
        tables.append({'table': 'game_product_config', 'values': data})
    alias_exists = product is not None and conn.scalar(select(GameAlias.alias_id).where(
        GameAlias.gpc_id == gpc, GameAlias.alias == row['raw_name'])) is not None
    if not alias_exists:
        tables.append({'table': 'game_alias', 'values': {'alias': row['raw_name']}})
    if not existing_quote(conn, row):
        tables.append({'table': 'm_low_record', 'values': {'gpc_id': gpc, **{k: q.get(k) for k in
            ('region', 'lowprice_cny', 'lowprice_method', 'lowprice_date')}}})
    return tables


def stored_records(conn, row):
    receipt = row.get('receipt') or {}
    record_id = receipt.get('record_id')
    if not record_id:
        return [{'table': '入库记录', 'values': {'说明': '旧回执缺少报价主键，无法核实已增数据'}, 'stored': True}]
    quote = conn.execute(select(PriceRecord.__table__).where(PriceRecord.record_id == record_id)).mappings().first()
    if not quote:
        return [{'table': '入库记录', 'values': {'说明': '回执对应的报价记录不存在'}, 'stored': True}]
    gpc = quote['gpc_id']
    product = conn.execute(select(GameProductConfig.__table__).where(GameProductConfig.gpc_id == gpc)).mappings().first()
    alias = conn.execute(select(GameAlias.__table__).where(GameAlias.gpc_id == gpc, GameAlias.alias == row['raw_name'])).mappings().first()
    added = receipt.get('added')
    result = []
    for table, record in [('game_product_config', product), ('game_alias', alias), ('m_low_record', quote)]:
        if record:
            label = '新增' if added and table in added else '复用' if added is not None else '新增/复用未记录'
            result.append({'table': table, 'stored': True, 'operation': label,
                           'values': {k: v for k, v in record.items() if v is not None and v != ''}})
    return result
