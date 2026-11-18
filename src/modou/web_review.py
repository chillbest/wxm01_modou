"""Validation shared by the online editor and its import boundary."""
from decimal import Decimal, InvalidOperation
from datetime import date

from .models import GPC_TYPES

REGIONS = ('国行', '港版', '美版', '欧版', '韩版', '日版', '海外版')
METHODS = ('直接购买', '福袋8折减80', '积/v3', '凑-50', '积-50')
PLATFORMS = ('PS5', 'PS4')


def eligibility_errors(row):
    """Validate required product and quote fields at the approval boundary."""
    final = row.get('final') or {}
    from .blacklist import is_blacklisted
    if is_blacklisted(row):
        return ['黑名单条目不可入库']
    quote = row.get('quote') or {}
    errors = []
    if final.get('outlink'):
        from .bangumi import valid_product_link
        if not valid_product_link(final['outlink']):
            errors.append('外链无效')
    if not (final.get('gpc_id') or final.get('bangumi_id') or final.get('outlink')):
        errors.append('命中目标待确认')
    if not final.get('gpc_id') and not str(final.get('name_zh') or '').strip():
        errors.append('游戏名称待确认')
    if not str(final.get('name_en') or '').strip():
        errors.append('英文名待确认')
    main = final.get('bangumi_main')
    from .main_ids import normalize_main
    try:
        if not normalize_main(main) and not (main is None and row.get('main_explicit_null') is True):
            errors.append('main待确认')
    except ValueError:
        errors.append('main待确认')
    if final.get('type') not in GPC_TYPES:
        errors.append('type待确认')
    if quote.get('platform') not in PLATFORMS:
        errors.append('平台待确认')
    if quote.get('region') not in REGIONS:
        errors.append('地区待确认')
    try:
        price = Decimal(str(quote.get('lowprice_cny')))
        if not price.is_finite() or price <= 0 or price >= 100000000 or price != price.quantize(Decimal('.01')):
            raise ValueError()
    except (ValueError, InvalidOperation):
        errors.append('价格无效')
    if quote.get('lowprice_method') not in METHODS:
        errors.append('优惠方式待确认')
    try:
        date.fromisoformat(quote.get('lowprice_date') or '')
    except (ValueError, TypeError):
        errors.append('报价日期待确认')
    if not str(quote.get('source_path') or '').strip():
        errors.append('来源待确认')
    return errors
