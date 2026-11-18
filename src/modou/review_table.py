"""Human-readable ABC rows; evidence remains separate from approved payloads."""
from html import escape
import re

STAGES = ('alias', 'local', 'api', 'ds', 'gamefaqs')


def quote_platform(row):
    """An identified game is required before assigning a default platform."""
    raw = row.get('extracted', {}).get('raw_name', row.get('raw_name', ''))
    explicit_ps4 = bool(re.search(r'(?<![A-Za-z0-9])PS\s*4(?![A-Za-z0-9])', raw, re.I))
    hits = stage_hits(row)
    if not hits:
        return None
    selected = hits.get('gamefaqs') or hits.get('ds') or hits.get('alias') or hits.get('local') or hits.get('api')
    if row.get('ps_disc_filter') and selected:
        from .bangumi import ps_platforms
        platforms = ps_platforms(selected)
        if not platforms:
            return None
        if len(platforms) == 1:
            return next(iter(platforms))
        return 'PS4' if explicit_ps4 else 'PS5'
    if explicit_ps4:
        return 'PS4'
    if selected:
        info = selected.get('infobox', [])
        values = []
        if isinstance(info, list):
            for field in info:
                if field.get('key') == '平台':
                    value = field.get('value')
                    if isinstance(value, str):
                        values.append(value)
                    elif isinstance(value, list):
                        values += [v.get('v', '') for v in value if isinstance(v, dict)]
        elif isinstance(info, str):
            match = re.search(r'^\|平台\s*=\s*(.*?)(?=\n\||\n\}\}|\Z)', info, re.M | re.S)
            if match:
                values.append(match[1])
        platforms = ' '.join(values).upper()
        # Evidence of a PS4 release, without a PS5 release in the platform list.
        if re.search(r'PS4|PLAYSTATION\s*4', platforms) and not re.search(r'PS5|PLAYSTATION\s*5', platforms):
            return 'PS4'
    return 'PS5'


def table_open():
    """Identical geometry for the legend and every independent item table."""
    widths = (20, 36, 7, 6, 6, 11, 14)
    return ('<table style="width:100%;table-layout:fixed;border-collapse:collapse;overflow-wrap:anywhere;word-break:break-word">'
            '<colgroup>' + ''.join('<col style="width:' + str(width) + '%">' for width in widths) + '</colgroup>')


def cell(value):
    return escape(str(value if value is not None else '待确认')).replace('\n', '<br>')


def platform_text(candidate):
    info = candidate.get('infobox') or []
    if isinstance(info, list):
        values = [f.get('value') for f in info if f.get('key') == '平台']
        return ' / '.join(str(v.get('v', '')) if isinstance(v, dict) else str(v)
                          for value in values for v in (value if isinstance(value, list) else [value]) if v)
    match = re.search(r'^\|平台\s*=\s*(.*?)(?=\n\||\n\}\}|\Z)', str(info), re.M | re.S)
    if not match:
        return ''
    value = match[1].strip()
    if value.startswith('{'):
        return ' / '.join(re.findall(r'\[([^\]]+)\]', value))
    return value


def release_year(candidate):
    value = str(candidate.get('date') or '')
    match = re.match(r'^(\d{4})(?:\D|$)', value)
    if match:
        return match[1]
    info = candidate.get('infobox') or []
    if isinstance(info, list):
        value = ' '.join(str(f.get('value') or '') for f in info if f.get('key') == '发行日期')
    else:
        value = '\n'.join(re.findall(r'^\|发行日期\s*=([^\r\n]*)', info, re.M))
    match = re.search(r'(?<!\d)(\d{4})(?=年|[-/.]|$)', value.strip())
    return match[1] if match else ''


def subject_label(candidate, *, include_year=False):
    name = candidate.get('name_cn') or candidate.get('name_zh') or candidate.get('name') or '名称未知'
    year = release_year(candidate) if include_year else ''
    if year:
        name = year + ' · ' + name
    if candidate.get('outlink'):
        from .bangumi import valid_product_link
        if valid_product_link(candidate['outlink']):
            from urllib.parse import urlsplit
            host = urlsplit(candidate['outlink']).hostname
            site = 'GameFAQs' if host == 'gamefaqs.gamespot.com' else 'VGCollect' if host == 'vgcollect.com' else '外链'
            return '<a href="' + cell(candidate['outlink']) + '">' + cell(name) + '（' + site + '）</a>'
    sid = candidate.get('id') or candidate.get('bangumi_id')
    if sid is not None and str(sid).isascii() and str(sid).isdigit():
        return cell(name) + '（<a href="https://bgm.tv/subject/' + str(sid) + '">' + str(sid) + '</a>）'
    return cell(name)


def stage_hits(row):
    if 'stage_hits' in row:
        return row['stage_hits']
    # Legacy rows preserve final candidates, not the complete lookup trace.
    hits = {}
    candidates = row.get('candidates', [])
    if row.get('source') in ('alias', 'local') and len(candidates) == 1:
        hits[row['source']] = candidates[0]
    sid = (row.get('suggestion') or {}).get('bangumi_id')
    if sid is not None:
        selected = next((c for c in candidates if str(c.get('id')) == str(sid)), None)
        if selected:
            hits['ds'] = selected
    return hits


def problems(row):
    extracted = row.get('extracted', {})
    issues = list(row.get('errors', []))
    quote = row.get('quote', {})
    for key, label in [('platform', '平台'), ('region', '地区'), ('lowprice_cny', '价格'), ('lowprice_date', '日期')]:
        if quote.get(key) is None:
            issues.append(label + '待确认')
    for issue in extracted.get('issues', []):
        if issue not in ('游戏名称未匹配', '游戏名称匹配歧义', '版本待确认', 'AI建议待人工确认', '平台待确认', '地区待确认', '日期待确认'):
            issues.append(issue)
    suggestion = row.get('suggestion')
    if suggestion is not None and suggestion.get('bangumi_id') is None and not row.get('gamefaqs_suggestion'):
        issues.append(suggestion.get('reason') or '名称未确定')
    hits = stage_hits(row)
    if 'gamefaqs' in hits:
        issues.append('GameFAQs链接待人工核实')
    if not hits and not issues:
        issues.append('名称未确定')
    edition = extracted.get('edition')
    selected = hits.get('gamefaqs') or hits.get('ds') or hits.get('local') or hits.get('alias') or hits.get('api')
    if edition and selected:
        name = str(selected.get('name_cn') or selected.get('name_zh') or selected.get('name') or '')
        variants = ('完全版', '完整版') if edition == '完全版' else (edition,)
        if not any(v.casefold() in name.casefold() for v in variants):
            issues.append('原文版本：' + edition + '；候选名称未明确体现该内容版本，须核实独立GPC，不能直接并入本体')
    return list(dict.fromkeys(i for i in issues if i))


def render_review(rows, title='笔记人工审核表'):
    lines = ['# ' + title, '', '全部待人工确认，未入库。未注明内容版本默认标准版（主版本）。', '',
             '命中依次为：别名库/本地BGM库/API/DeepSeek辅助/GameFAQs。`-`表示没有可证实的唯一命中；候选不等于命中。', '',
             table_open(), '<thead><tr>' + ''.join('<th>' + h + '</th>' for h in
             ('解析得原名', '命中（别名库/本地BGM库/API/DeepSeek辅助/GameFAQs）', '平台', '地区', '价格', '优惠方式', '问题简述')) + '</tr></thead>',
             '</table>', '']
    for index, row in enumerate(rows, 1):
        quote = row.get('quote', {})
        raw = row.get('extracted', {}).get('raw_line', row['raw_name'])
        hits = stage_hits(row)
        issues = problems(row)
        description = '；'.join(issues)
        short = description if len(description) <= 10 else '详见下行'
        lines += ['（' + str(index) + '）' + cell(raw), '', table_open(), '<tbody>']
        values = [cell(row['raw_name']), '/'.join(subject_label(hits[s]) if s in hits else '-' for s in STAGES),
                  *[cell(quote.get(k)) for k in ('platform', 'region', 'lowprice_cny', 'lowprice_method')], cell(short or '-')]
        lines.append('<tr>' + ''.join('<td>' + v + '</td>' for v in values) + '</tr>')
        if len(description) > 10:
            lines.append('<tr><td colspan="7">——' + '<br>'.join(cell(i) for i in issues) + '</td></tr>')
        lines += ['</tbody>', '</table>', '']
    return '\n'.join(lines)
