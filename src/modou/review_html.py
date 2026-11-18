"""Standalone night-mode human review. No remote assets or business writes."""
from html import escape
import re
import hashlib
import json
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo
from .review_table import cell, stage_hits, subject_label, release_year, problems, STAGES
from .models import GPC_TYPES
from .publication_date import infer_publication_date

COLORS = dict(alias='#2ECC71', local='#00C2D1', api='#2F80ED', ds='#9B51E0', gamefaqs='#FF6FAE')


def original_with_section(row):
    extracted = row.get('extracted', {})
    raw = extracted.get('raw_line', row.get('raw_name', ''))
    section = str(extracted.get('section') or '')
    # Keep the actual block wording, removing only decorative boundary glyphs.
    section = re.sub(r'^[^\w\u3400-\u9fff]+|[^\w\u3400-\u9fff]+$', '', section).strip()
    return raw.rstrip() + (f'（{section}）' if section else '')
HEADERS = ('解析得原名', '命中（别名库/本地BGM库/API/DeepSeek辅助/GameFAQs）', 'main', 'type', '平台', '地区', '价格', '优惠方式')


def gpc_fields(row, hits):
    """Use saved GPC fields; never infer a main subject or default product type."""
    final = row.get('final') or {}
    selected = next((hits[s] for s in reversed(STAGES) if s in hits), {})
    if any(final.get(key) is not None and str(final[key]) != str(selected.get(key))
           for key in ('gpc_id', 'bangumi_id')):
        selected = {}
    bangumi_main = final.get('bangumi_main') if final.get('bangumi_main') is not None else selected.get('bangumi_main')
    # Bangumi subjects also have `type` (4 = game). Only a saved GPC carries
    # our product classification; subject metadata must never supply it.
    gpc_type = final.get('type')
    if gpc_type is None and selected.get('gpc_id') is not None:
        gpc_type = selected.get('type')
    main_result = row.get('main_resolution') or {}
    if bangumi_main is None and str(main_result.get('subject_id')) == str(selected.get('id') or selected.get('bangumi_id')):
        bangumi_main = main_result.get('main_id')
    return bangumi_main, gpc_type if gpc_type in GPC_TYPES else None


def main_subject_link(value, subject_id=None):
    if value is None or value == '':
        return '<span style="background:#F53535;color:#000;font-weight:700">？</span>'
    if isinstance(value, str) and '|' in value:
        return ' | '.join(main_subject_link(part, subject_id) for part in value.split('|'))
    sid = str(value)
    if sid.isascii() and sid.isdigit():
        if subject_id is not None and sid == str(subject_id):
            return '<span style="color:#64748B">（' + sid + '）</span>'
        return '<a href="https://bgm.tv/subject/' + sid + '" target="_blank" rel="noopener noreferrer">（' + sid + '）</a>'
    return cell(value)


def type_dropdown(value):
    if value not in GPC_TYPES:
        value = None
    options = [(None, '待确认'), *((t, t) for t in GPC_TYPES)]
    return ('<select class="gpc-type" aria-label="GPC type" disabled>'
            + ''.join('<option value="' + escape(str(key or ''), quote=True) + '"'
                      + (' selected' if key == value else '') + '>' + cell(label) + '</option>'
                      for key, label in options) + '</select>')


def interaction_summary(row, index, stage_name):
    """Three information items from saved evidence; never infer missing AI choices."""
    def plain(value):
        return escape(' '.join(str(value).split()))
    def badge(candidate, selected=False):
        label = candidate.get('name_cn') or candidate.get('name_zh') or candidate.get('name') or '名称未知'
        year = release_year(candidate)
        if year:
            label = year + ' · ' + label
        sid = candidate.get('id') or candidate.get('bangumi_id')
        if sid is not None:
            if selected:
                id_html = '<u>' + plain(sid) + '</u>'
            elif str(sid).isascii() and str(sid).isdigit():
                id_html = '<a href="https://bgm.tv/subject/' + str(sid) + '" target="_blank" rel="noopener noreferrer">' + plain(sid) + '</a>'
            else:
                id_html = plain(sid)
            label_html = plain(label) + '（' + id_html + '）'
        else:
            label_html = plain(label)
        return '<code class="ai-summary-badge' + (' ai-summary-selected' if selected else '') + '">' + label_html + '</code>'
    trace = row.get('stage_trace', [])
    evidence = next((t for stage in ('BangumiAPI', 'Bangumi本地资料') for t in reversed(trace)
                     if t.get('stage') == stage and t.get('candidates') and t.get('result') != '未执行'), None)
    if evidence:
        origin = 'BGM API' if evidence['stage'] == 'BangumiAPI' else 'BGM本地'
        second_label = origin + evidence['result'] + '：'
        second = ' '.join(badge(c) for c in evidence['candidates'])
    else:
        second_label, second = 'BGM候选：', '本次候选详情未记录'
    chosen = stage_hits(row).get('ds' if stage_name == 'DeepSeek' else 'gamefaqs')
    label = 'DeepSeek选择：' if stage_name == 'DeepSeek' else 'GameFAQs建议：'
    if chosen:
        third = badge(chosen, True)
    else:
        event = next((t for t in reversed(trace) if t.get('stage') == stage_name), None)
        third = plain(('未选择候选' if event['result'] == '未命中' else event['result']) if event else '本次选择未记录')
    original = original_with_section(row)
    return ('<ul class="ai-summary"><li class="ai-summary-item"><div class="ai-summary-line"><span class="ai-summary-original">'
            + plain(str(index) + '. ' + original) + '</span></div></li><li class="ai-summary-item"><div class="ai-summary-line">'
            + '<span class="ai-summary-label">' + plain(second_label) + '</span><span class="ai-summary-value">' + second + '</span></div></li><li class="ai-summary-item"><div class="ai-summary-line">' + '<span class="ai-summary-label">' + plain(label) + '</span><span class="ai-summary-value">' + third + '</span></div></li></ul>')


def publication_day(source, title, now):
    day = infer_publication_date(source, title, now)
    if day is None:
        raise ValueError('文件名或标题无可识别的出价日期')
    return day



def header_stage_label(key, label):
    text = cell(label)
    if key == 'gamefaqs':
        text = '<a href="https://vgcollect.com/search" target="_blank" rel="noopener noreferrer" style="color:inherit">' + text + '</a>'
    return '<span class="stage-label" style="background:' + COLORS[key] + ';color:#000">' + text + '</span>'

def adaptive_hit_header():
    versions = [
        (['别名库','本地BGM库','API','DeepSeek辅助','GameFAQs'], ' / ', '（', '）⛔'),
        (['别名库','本地BGM库','API','DeepSeek辅助','GameFAQs'], ' / ', '（', '）'),
        (['别名库','本地BGM库','API','DeepSeek','FAQs'], ' / ', '（', '）'),
        (['别名库','本地BGM库','API','DeepSeek','FAQs'], '/', '(', ')'),
        (['别名库','本地BGM库','API','DS','FAQs'], '/', '(', ')'),
        (['别名','本地','API','DS','FAQ'], '/', '(', ')'),
    ]
    choices = ['命中' + left + sep.join(
        header_stage_label(key, label)
        for key, label in zip(('alias','local','api','ds','gamefaqs'), labels)) + right
        for labels, sep, left, right in versions]
    return '<script id="adaptive-hit-header">' + """
(() => {
  const header = document.querySelector('.sticky-header th:nth-child(2)');
  const choices = CHOICES;
  const probe = document.createElement('span');
  probe.style.cssText = 'position:fixed;visibility:hidden;pointer-events:none;white-space:nowrap;width:max-content;left:0;top:0';
  header.appendChild(probe);
  const widths = [];
  function fitHeader() {
    const style = getComputedStyle(header);
    const available = header.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    let selected = choices.length - 1;
    for (let i = 0; i < choices.length; i++) {
      probe.innerHTML = choices[i];
      widths[i] = probe.getBoundingClientRect().width;
      if (widths[i] <= available) { selected = i; break; }
    }
    header.innerHTML = choices[selected];
    header.style.whiteSpace = widths[selected] <= available ? 'nowrap' : 'normal';
    header.dataset.variant = String(selected + 1);
    header.appendChild(probe);
  }
  fitHeader();
  new ResizeObserver(fitHeader).observe(header);
  window.addEventListener('resize', fitHeader);
  if (document.fonts) document.fonts.ready.then(fitHeader);
})();
""".replace('CHOICES', json.dumps(choices, ensure_ascii=False)) + '</script>'

def render_html(rows, title, day, *, start_index=1, online=False):
    cols = '<colgroup>' + ''.join(f'<col style="width:{w}%">' for w in (18,35,10,10,6.3,5.4,5.4,9.9)) + '</colgroup>'
    parts = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
             '<base target="_blank"><title>' + cell(title) + '</title><style>.gpc-type:disabled{width:100%;min-width:0;background:#374151;color:#9ca3af;border:1px solid #64748b;border-radius:4px;padding:4px;font:inherit;opacity:1;-webkit-text-fill-color:#9ca3af;cursor:not-allowed;text-align:center;text-align-last:center}.gpc-type option{text-align:center}body{margin:0;background:#111827;color:#e5e7eb;font:16px/1.6 system-ui,"Microsoft YaHei",sans-serif}main{padding:24px 100px;max-width:1800px;margin:auto}table{width:100%;table-layout:fixed;border-collapse:collapse}th,td{border:1px solid #4b5563;padding:10px;overflow-wrap:anywhere}th{background:#253343;text-align:center}td{text-align:center}.detail td{text-align:left}.hit-muted{color:#9ca3af}.matched-gold{display:inline-block;background:#493817;color:#ffe49c;border:2px solid #e5b94f;box-shadow:0 0 12px #e5b94f26;border-radius:6px;font:inherit;font-weight:700;padding:3px 8px;margin:2px}.matched-gold a{color:#ffe49c}.stage-label{display:inline-block;color:#000;border-radius:4px;padding:1px 5px;margin:2px}.candidate-code{display:inline-block;background:#26364b;color:#f8d78b;border:1px solid #475569;border-radius:5px;padding:1px 6px;margin:2px 3px;font:inherit}.candidate-code a{color:#9bdbff}.alias-preview-code{background:#1b2939;color:#91a8be;border-radius:4px;padding:2px 7px;font:inherit}.alias-preview-note{color:#91a8be}a{color:#7dd3fc}.entry{margin-top:24px;margin-bottom:32px}.children{margin-left:20px}.original{font-size:18px;font-weight:600;font-style:italic;margin:0 0 10px}.detail{background:#182232}.trace{color:#b9c8db;font-size:16px;padding:12px 0;margin-left:calc(18% + 10px);display:grid;grid-template-columns:max-content 1fr;column-gap:12px}.trace-label{grid-column:1;grid-row:1}.trace-line{grid-column:2;display:grid;grid-template-columns:10em minmax(0,1fr);column-gap:0.25em}.trace-unmatched,.trace-unmatched *{color:#64748b!important}.trace-stage{text-align:right;white-space:pre}.trace-stage-name{font-size:14px;font-weight:700}body.hide-c.hide-d .entry{margin-top:10px;margin-bottom:12px}body.hide-c.hide-d .original{margin-bottom:5px}body.hide-c.hide-d .b-row td{padding-top:2px;padding-bottom:2px;line-height:1.25}body.hide-c.hide-d .b-row .matched-gold{padding-top:0;padding-bottom:0;margin-top:0;margin-bottom:0;line-height:1.25}.trace-content{min-width:0}.sticky-header{position:sticky;top:0;z-index:20;background:#111827;padding:8px 0}.toolbar{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:8px}.toolbar button{background:#253343;color:#e5e7eb;border:1px solid #64748b;padding:7px 12px;cursor:pointer}.pingpong{display:inline-flex;align-items:center;gap:10px}.pingpong::after{content:"";width:40px;height:22px;flex-shrink:0;border-radius:20px;background:radial-gradient(circle at 11px 11px,#fff 0 8px,transparent 9px),#64748b;transition:background .15s}.pingpong[aria-checked="true"]::after{background:radial-gradient(circle at 29px 11px,#fff 0 8px,transparent 9px),#22c55e}.pingpong:focus-visible{outline:2px solid #7dd3fc;outline-offset:3px}.original input{margin-right:10px;accent-color:#22c55e}.entry[hidden]{display:none}body.hide-c .detail{display:none}body.hide-d .trace{display:none}.toolbar{display:grid;grid-template-columns:1fr auto 1fr;align-items:center}.selection-controls{display:flex;gap:10px;grid-column:1;grid-row:1}.detail-controls{grid-column:2;grid-row:1;display:flex;justify-content:center;gap:10px}.toolbar .export-button{grid-column:3;grid-row:1;justify-self:end}.toolbar>.toolbar-status{grid-column:1/-1}.export-footer{display:grid;grid-template-columns:1fr 1fr 1fr;align-items:center}.export-footer #copy-export{justify-self:start}.export-footer #export-count{text-align:center}.export-footer #close-export{justify-self:end}#copy-status{display:block;min-height:1.6em}.detail-controls button{white-space:nowrap}@media(max-width:1000px){.toolbar{display:flex}.detail-controls{width:100%;order:2}.toolbar .export-button{margin-left:auto}}dialog{background:#182232;color:#e5e7eb;border:1px solid #64748b;width:min(900px,90vw);border-radius:8px}dialog::backdrop{background:#0009}dialog textarea{box-sizing:border-box;width:100%;height:55vh;background:#111827;color:#e5e7eb;padding:12px;font:16px/1.6 monospace}dialog button{margin:10px 10px 0 0;padding:8px 16px}.b-row td{text-align:center}.toolbar-status{align-self:center;font-size:13px}.platform{color:#000;font-weight:700;text-align:center}@media(max-width:700px){main{padding:10px}.children{margin-left:8px}th,td{padding:5px;font-size:16px}}.sticky-header,.sticky-header *{font-size:13px}</style></head><body><main>',
             '<h1>' + cell(title) + '</h1><p>出价日' + (day.strftime('%Y/%m/%d') if day else '待确认') + ' · 全部待人工审核 · 未入库</p>',

             '<div class="sticky-header"><div class="toolbar"><span class="selection-controls"><button type="button" id="clear-selection">🧹 清除全部</button><button type="button" id="show-unchecked" class="pingpong" role="switch" aria-checked="false">⬜ 仅看未选</button><button type="button" id="show-all">👁️ 显示全部</button></span><span class="detail-controls"><button type="button" id="toggle-c" class="pingpong" role="switch" aria-checked="true">C行=问题详情</button><button type="button" id="toggle-d" class="pingpong" role="switch" aria-checked="true">D行=命中详情</button><button type="button" id="show-details">显示全部详情</button></span><button type="button" id="export-unchecked" class="export-button">↗️ 导出ALL未选</button><span class="toolbar-status" id="selection-status" aria-live="polite"></span></div><div class="children"><table>' + cols + '<thead><tr>' + ''.join('<th>'+h+'</th>' for h in (HEADERS[0], '命中（' + ' / '.join(header_stage_label(key, label) for key,label in [('alias','别名库'),('local','本地BGM库'),('api','API'),('ds','DeepSeek辅助'),('gamefaqs','GameFAQs')]) + '）', *HEADERS[2:])) + '</tr></thead></table></div></div>']
    for index, row in enumerate(rows,start_index):
        hits = stage_hits(row); quote = row['quote']
        display_row = row if hits else {**row, 'quote': {**quote, 'platform': None}}
        issues = problems(display_row)
        bangumi_main, gpc_type = gpc_fields(row, hits)
        color = next((COLORS[s] for s in reversed(STAGES) if s in hits), '#F53535')
        parts += ['<section class="entry"><p class="original"><label><input type="checkbox" class="review-check" aria-label="勾选条目' + str(index) + '">' + str(index) + '. ' + cell(original_with_section(row)) + '</label></p><div class="children">', '<table>'+cols+'<tbody><tr class="b-row">']
        values = [cell(row['raw_name']), '<span class="hit-muted"> / </span>'.join('<code class="matched-gold">' + subject_label(hits[s]).replace('<a ', '<a target="_blank" rel="noopener noreferrer" ') + '</code>' if s in hits else '<span class="hit-muted">-</span>' for s in STAGES), main_subject_link(bangumi_main, (row.get('final') or {}).get('bangumi_id') or next((hits[s].get('bangumi_id') or hits[s].get('id') for s in reversed(STAGES) if s in hits), None)), type_dropdown(gpc_type), cell(quote.get('platform')) if hits and quote.get('platform') else '？', cell(quote.get('region')),cell(quote.get('lowprice_cny')),cell(quote.get('lowprice_method'))]
        for i,v in enumerate(values):
            if i == 0:
                opening = '<td class="hit-name" style="background:' + color + ';color:#000">'
            elif i == 2 and bangumi_main in (None, ''):
                opening = '<td class="main-unknown" style="background:#F53535;color:#000;font-weight:700">'
            elif i == 4 and (not hits or not quote.get('platform')):
                opening = '<td class="platform" style="background:#F53535;color:#000">'
            elif i == 4 and quote.get('platform') == 'PS4':
                opening = '<td class="platform" style="background:#64748B;color:#000">'
            else:
                opening = '<td>'
            parts.append(opening + v + '</td>')
        parts.append('</tr>')
        if issues:
            parts.append('<tr class="detail"><td colspan="8">——'+'<br>'.join(cell(i) for i in issues)+'</td></tr>')
        parts.append('</tbody></table><div class="trace"><span class="trace-label">【命中情况】</span>')
        trace = row.get('stage_trace',[])
        for name in ('本地别名','Bangumi本地资料','BangumiAPI','DeepSeek','GameFAQs'):
            events = [t for t in trace if t['stage']==name]
            if events and all(t['result'] == '未执行' and '命中' in t['reason'] for t in events):
                continue
            label = {'本地别名':'别名库','Bangumi本地资料':'BGM 本地','BangumiAPI':'BGM API','DeepSeek':'DeepSeek','GameFAQs':'GameFAQs'}[name]
            alias_preview = ''
            target = hits.get('gamefaqs') or hits.get('ds') or hits.get('api') or hits.get('local')
            if not online and name == '本地别名' and events and all(t['result'] == '未命中' for t in events) and target:
                target_name = target.get('name_zh') or target.get('name_cn') or target.get('name')
                if target_name:
                    alias_preview = ' <span class="alias-preview-note">—— （拟增）<code class="alias-preview-code">' + cell(row['raw_name']) + '</code> → <code class="alias-preview-code">' + cell(target_name) + '</code></span>'
            if name in ('DeepSeek', 'GameFAQs') and row.get('ai_mode') != 'batch':
                records = [r for r in row.get('ai_interactions', []) if r.get('stage') == name or name == 'GameFAQs' and r.get('stage') == 'GameFAQs主版本']
                detail = [interaction_summary(row, index, name)]
                for record in records:
                    detail.append('<p class="ai-call">调用：' + escape(str(record.get('call_id', ''))) + '</p>')
                    for number, (key, heading) in enumerate([('system','System提示词'), ('user','User内容'), ('content','模型回复原文'), ('raw_response','HTTP响应原文')], 1):
                        value = record.get(key)
                        if value is None:
                            value = '未收到或无法提取；' + str(record.get('error') or '无正文')
                        detail.append('<section class="ai-block' + (' ai-reply' if key == 'content' else '') + '"><h3><span>' + f'{number:02d}' + '</span> ' + heading + '<button type="button" class="ai-block-wrap" aria-label="换行" title="换行"></button></h3><pre>' + escape(value) + '</pre></section>')
                    detail.append('<p class="ai-call">状态：' + escape(str(record.get('status'))) + '；' + escape(str(record.get('error') or '')) + '</p>')
                detail_html = ''.join(detail) + ('' if records else '<p>本次交互详情未记录</p>')
                parts.append('<template id="ai-' + str(index) + '-' + name + '">' + detail_html + '</template>')
            parts.append('<span class="trace-line' + (' trace-unmatched' if events and all(t['result'] == '未命中' for t in events) else '') + '">'+'<span class="trace-stage">'+'<span class="trace-stage-name"' + (' style="background:' + COLORS[{'本地别名':'alias','Bangumi本地资料':'local','BangumiAPI':'api','DeepSeek':'ds','GameFAQs':'gamefaqs'}[name]] + ';color:#000;border-radius:4px"' if {'本地别名':'alias','Bangumi本地资料':'local','BangumiAPI':'api','DeepSeek':'ds','GameFAQs':'gamefaqs'}[name] in hits else '') + '>'+cell(label)+'</span> —— </span><span class="trace-content">'+('<br>'.join(((' <span tabindex="0" class="ai-trigger" data-detail="ai-' + str(index) + '-' + name + '">' + cell(t['result']) + '</span>') if name in ('DeepSeek','GameFAQs') and row.get('ai_mode') != 'batch' else cell(t['result'])) + cell('' if (t['result'] in ('命中', '歧义') and t.get('candidates')) or (t['result'],t['reason']) in (('未命中','无匹配候选'),('命中','唯一候选'),('歧义','多个候选')) else '；'+t['reason']) + (('：' if t['result'] in ('命中', '歧义') else '<br>候选：') + '；'.join('<code class="candidate-code">' + subject_label({**next((full for full in row.get("candidates", []) if str(full.get("id") or full.get("bangumi_id")) == str(c.get("id") or c.get("bangumi_id"))), {}), **c}, include_year=True).replace('<a ', '<a target="_blank" rel="noopener noreferrer" ') + (' [GPC ' + cell(c['gpc_id']) + ']' if c.get('gpc_id') is not None else '') + '</code>' for c in t['candidates']) if t.get('candidates') else ('<br>候选详情未记录' if t['result'] == '歧义' else '')) for t in events) if events else '未记录，不能据此判定未命中')+alias_preview+'</span></span>')
        parts.append('</div></div>')
        if row.get('ai_group'):
            from .ai_review import group_html
            parts.append(group_html(row['ai_group']))
        parts.append('</section>')
    parts.append('<style>\n.ai-trigger{cursor:help;text-decoration:underline dotted}.ai-popup{position:fixed;z-index:100;box-sizing:border-box;width:min(900px,94vw);max-height:70vh;overflow-y:auto;overflow-x:hidden;background:#0f172a;color:#e5e7eb;border:1px solid #94a3b8;border-radius:8px;padding:14px;box-shadow:0 8px 32px #0009;user-select:text}.ai-popup pre{white-space:pre;overflow-wrap:normal;font:14px/1.5 Consolas,monospace;margin:0;padding:12px 14px;overflow-x:auto;overflow-y:hidden;max-height:none}.ai-block{min-width:0;background:#131f33;border:1px solid #3a4b63;border-radius:9px;margin:14px 0;overflow:hidden}.ai-block h3{font:600 14px/1.6 system-ui;margin:0;padding:10px 13px;background:#20324c;border-bottom:1px solid #3a4b63}.ai-block h3 span{font:12px monospace;opacity:.75;margin-right:8px}.ai-block.ai-reply{background:#34252f;border-color:#8a6277}.ai-block.ai-reply h3{background:#493440}.ai-block-wrap{display:inline-flex;align-items:center;justify-content:center;vertical-align:middle;margin-left:12px;padding:4px 6px;background:transparent;color:#e2e8f0;border:1px solid #536783;border-radius:6px;cursor:pointer}.ai-block-wrap[aria-pressed="true"]{background:#36517c}.ai-tools #ai-close{display:inline-flex;align-items:center;justify-content:center}.ai-call{font:12px/1.5 system-ui;color:#a6b5cb;overflow-wrap:anywhere;margin:3px 0 6px}.ai-tools{position:sticky;top:-14px;background:#0f172a;padding:10px 0;z-index:1;display:flex;justify-content:flex-start;gap:8px;flex-wrap:wrap}.ai-tools button{font:14px system-ui;padding:6px 10px;background:#243149;color:#e2e8f0;border:1px solid #52617a;border-radius:6px}.ai-popup,.ai-popup pre{color-scheme:dark;scrollbar-color:#9e9e9e #2b2b2b}.ai-popup::-webkit-scrollbar,.ai-popup pre::-webkit-scrollbar{width:12px;height:12px}.ai-popup::-webkit-scrollbar-track,.ai-popup pre::-webkit-scrollbar-track{background:#2b2b2b}.ai-popup::-webkit-scrollbar-thumb,.ai-popup pre::-webkit-scrollbar-thumb{background:#9e9e9e;border:2px solid #2b2b2b;border-radius:8px}.ai-popup::-webkit-scrollbar-thumb:hover,.ai-popup pre::-webkit-scrollbar-thumb:hover{background:#b5b5b5}.ai-popup::-webkit-scrollbar-corner,.ai-popup pre::-webkit-scrollbar-corner{background:#2b2b2b}.ai-popup[hidden]{display:none}\n.ai-summary{font:12px/1.5 system-ui;color:#a6b5cb;display:grid;gap:3px;padding:4px 0 0 18px;margin:0;list-style-type:disc;min-width:0}.ai-summary-line{display:grid;grid-template-columns:max-content minmax(0,1fr);align-items:baseline;min-width:0;white-space:normal}.ai-summary-item:first-child .ai-summary-line{display:block;overflow-wrap:anywhere}.ai-summary-item{min-width:0}.ai-summary-label{white-space:nowrap}.ai-summary-value{min-width:0;overflow-wrap:anywhere}.ai-summary-original{display:inline;background:#fff;color:#000;font-size:14px;font-weight:700;font-style:italic;padding:4px 8px;box-decoration-break:clone;-webkit-box-decoration-break:clone}.ai-summary-badge{display:inline-block;max-width:100%;box-sizing:border-box;white-space:normal;overflow-wrap:anywhere;background:#26364b;color:#f8d78b;border:1px solid #475569;border-radius:5px;padding:2px 6px;margin-right:6px;margin-bottom:0;font:inherit}.ai-summary-badge a{color:#9bdbff;text-decoration:underline}.ai-summary-badge.ai-summary-selected{color:#a6b5cb;background:#493817;border:2px solid #e5b94f;font-weight:700;box-shadow:0 0 12px #e5b94f26}</style><aside id="ai-popup" class="ai-popup" hidden aria-label="DeepSeek交互详情"><div class="ai-tools"><button type="button" id="ai-close" aria-label="关闭交互详情" title="关闭"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg></button><button type="button" id="ai-format">JSON格式化</button><button type="button" id="ai-wrap">All换行</button></div><div id="ai-text"></div></aside>\n<script>\n(() => {\n const popup=document.querySelector(\'#ai-popup\'), text=document.querySelector(\'#ai-text\');\n let timer, formatted=false;\n const keep=()=>clearTimeout(timer);\n const hide=()=>{timer=setTimeout(()=>{popup.hidden=true;},200);};\n function show(trigger){\n  keep(); text.replaceChildren(document.getElementById(trigger.dataset.detail).content.cloneNode(true));\n  text.querySelectorAll(\'pre\').forEach(pre=>{\n   pre.original=pre.textContent; pre.wrapped=false;\n   pre.parentElement.querySelector(\'.ai-block-wrap\').onclick=()=>{pre.wrapped=!pre.wrapped;render();};\n  }); formatted=false; render();\n  text.querySelectorAll(\'[data-ai-tab]\').forEach(tab=>{tab.onclick=()=>{text.querySelectorAll(\'[data-ai-tab]\').forEach(t=>t.setAttribute(\'aria-selected\',String(t===tab)));text.querySelectorAll(\'[data-ai-panel]\').forEach(p=>{p.hidden=p.dataset.aiPanel!==tab.dataset.aiTab;});};});\n  popup.hidden=false;\n  const r=trigger.getBoundingClientRect();\n  popup.style.left=Math.max(8,Math.min(r.left,innerWidth-popup.offsetWidth-8))+\'px\';\n  popup.style.top=Math.max(8,Math.min(r.bottom+6,innerHeight-popup.offsetHeight-8))+\'px\';\n  if(trigger.dataset.detail.startsWith(\'ai-group-\')){popup.style.left=Math.max(8,Math.min((r.left+r.right-popup.offsetWidth)/2,innerWidth-popup.offsetWidth-8))+\'px\';popup.style.top=Math.max(8,r.top-popup.offsetHeight-8)+\'px\';}\n\n }\n document.addEventListener(\'mouseover\',e=>{const t=e.target.closest(\'.ai-trigger\');if(t&&!t.contains(e.relatedTarget)&&!t.closest(\'.web-locked\'))show(t);});\n document.addEventListener(\'mouseout\',e=>{if(e.target.closest(\'.ai-trigger\'))hide();});\n document.addEventListener(\'focusin\',e=>{const t=e.target.closest(\'.ai-trigger\');if(t&&!t.contains(e.relatedTarget)&&!t.closest(\'.web-locked\'))show(t);});\n document.addEventListener(\'focusout\',e=>{if(e.target.closest(\'.ai-trigger\'))hide();});\n popup.addEventListener(\'mouseenter\',keep);popup.addEventListener(\'mouseleave\',hide);\n popup.addEventListener(\'focusin\',keep);\n document.querySelector(\'#ai-close\').onclick=()=>{keep();popup.hidden=true;};\n document.addEventListener(\'keydown\',e=>{if(e.key===\'Escape\'){keep();popup.hidden=true;}});\n function render(){\n  text.querySelectorAll(\'pre\').forEach(pre=>{\n   let value=pre.original;\n   if(formatted){try{value=JSON.stringify(JSON.parse(value),null,2);}catch{}}\n   pre.textContent=value;\n   pre.style.whiteSpace=pre.wrapped ? \'pre-wrap\' : \'pre\';\n   pre.style.overflowWrap=pre.wrapped ? \'anywhere\' : \'normal\';\n   const button=pre.parentElement.querySelector(\'.ai-block-wrap\');\n   const action=pre.wrapped ? \'不换行\' : \'换行\';\n   button.setAttribute(\'aria-label\',action); button.setAttribute(\'title\',action);\n   button.setAttribute(\'aria-pressed\',String(pre.wrapped));\n   button.innerHTML=\'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">\'+(pre.wrapped ? \'<path d="M4 12h16m-5-5 5 5-5 5"/>\' : \'<path d="M3 6h18M3 12h13a4 4 0 0 1 0 8h-4m3-3-3 3 3 3M3 18h3"/>\')+\'</svg>\';\n\n  });\n  document.querySelector(\'#ai-format\').textContent=formatted ? \'还原JSON原文\' : \'JSON格式化\';\n  document.querySelector(\'#ai-wrap\').textContent=text.querySelectorAll(\'pre\').length && [...text.querySelectorAll(\'pre\')].every(pre=>pre.wrapped) ? \'All不换行\' : \'All换行\';\n }\n document.querySelector(\'#ai-format\').onclick=()=>{formatted=!formatted;render();};\n document.querySelector(\'#ai-wrap\').onclick=()=>{const pres=[...text.querySelectorAll(\'pre\')];const next=!pres.every(pre=>pre.wrapped);pres.forEach(pre=>{pre.wrapped=next;});render();};\n})();\n</script>')
    if online:
        html = '\n'.join(parts + [adaptive_hit_header(), '</main></body></html>'])
        html = html.replace('⬜ 仅看未选', '仅看未选')
        html = html.replace('<button type="button" id="show-all">👁️ 显示全部</button>', '')
        return html
    return '\n'.join(parts+[adaptive_hit_header(), '''<dialog id="export-dialog" aria-labelledby="export-title"><h2 id="export-title">未勾选条目</h2><textarea id="export-text" aria-label="未勾选条目信息"></textarea><div class="export-footer"><button type="button" id="copy-export">复制全部内容</button><span id="export-count" role="status"></span><button type="button" id="close-export">关闭</button></div><span id="copy-status" role="status"></span></dialog><script>
(() => {
  const entries = [...document.querySelectorAll('.entry')];
  let onlyUnchecked = false;
  function update() {
    let checked = 0;
    entries.forEach(entry => {
      const selected = entry.querySelector('.review-check').checked;
      if (selected) checked++;
      entry.hidden = onlyUnchecked && selected;
    });
    document.querySelector('#selection-status').textContent = `已勾选${checked}/${entries.length}项 · ${onlyUnchecked ? '仅看未选' : '显示全部'}`;
    document.querySelector('#show-unchecked').setAttribute('aria-checked', String(onlyUnchecked));
    document.querySelector('#show-all').setAttribute('aria-pressed', String(!onlyUnchecked));
  }
  document.querySelector('#clear-selection').onclick = () => { entries.forEach(e => e.querySelector('.review-check').checked = false); update(); };
  document.querySelector('#show-unchecked').onclick = () => { onlyUnchecked = !onlyUnchecked; update(); };
  document.querySelector('#show-all').onclick = () => { onlyUnchecked = false; update(); };
  entries.forEach(e => e.querySelector('.review-check').addEventListener('change', update));
  const $ = selector => document.querySelector(selector);
  $('#toggle-c').onclick = () => { const hidden = document.body.classList.toggle('hide-c'); $('#toggle-c').setAttribute('aria-checked',String(!hidden)); };
  $('#toggle-d').onclick = () => { const hidden = document.body.classList.toggle('hide-d'); $('#toggle-d').setAttribute('aria-checked',String(!hidden)); };
  $('#show-details').onclick = () => { document.body.classList.remove('hide-c','hide-d'); $('#toggle-c').setAttribute('aria-checked','true'); $('#toggle-d').setAttribute('aria-checked','true'); };
  $('#export-unchecked').onclick = () => {
    const blocks = entries.filter(e => !e.querySelector('.review-check').checked).map(e => {
      const original = e.querySelector('.original label').textContent.trim();
      const cells = [...e.querySelectorAll('.b-row td')].map(c => c.textContent.trim());
      cells[1] = cells[1].split('/').map(part => { const value = part.trim().replace(/^✓\\s*/, ''); return value === '-' ? '_' : value; }).join('/');
      return original + '\\n' + [cells[0],cells[1],...cells.slice(4,8)].join('——');
    });
    $('#export-text').value = blocks.join('\\n\\n\\n');
    $('#export-count').textContent = `共${blocks.length}条`;
    $('#copy-status').textContent = '';
    $('#export-dialog').showModal();
  };
  $('#close-export').onclick = () => $('#export-dialog').close();
  $('#copy-export').onclick = async () => {
    const textarea = $('#export-text');
    try {
      try { await navigator.clipboard.writeText(textarea.value); }
      catch { textarea.focus(); textarea.select(); if (!document.execCommand('copy')) throw new Error('copy failed'); }
      $('#copy-status').textContent='已复制全部内容';
    } catch { $('#copy-status').textContent='自动复制失败，请选中文本后按Ctrl+C'; textarea.focus(); textarea.select(); }
  };
  update();
})();
</script></main></body></html>'''])


def read_html_metadata(path):
    match = re.search(r'<script id="review-metadata" type="application/json">(.*?)</script>',
                      Path(path).read_text(encoding='utf-8'), re.S)
    return json.loads(match[1]) if match else None


def write_html(rows, source, title, directory, now=None, *, parsed_at=None, revision_of=None):
    """New parse by default; revision_of preserves the original batch and parse time."""
    timezone = ZoneInfo('Asia/Shanghai')
    now = now or datetime.now(timezone)
    parsed_at = parsed_at or now
    if parsed_at.tzinfo is None:
        parsed_at = parsed_at.replace(tzinfo=timezone)
    parsed_at = parsed_at.astimezone(timezone)
    directory = Path(directory)
    content_hash = hashlib.sha256(json.dumps(
        {'rows': rows, 'source': source, 'title': title}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    previous = read_html_metadata(revision_of) if revision_of else None
    if previous:
        if previous['content_hash'] != content_hash:
            raise ValueError('审核内容不同，不能作为同一解析批次改版')
        parsed_at = datetime.fromisoformat(previous['parsed_at'])
        batch_id = previous['batch_id']
        revision = previous['revision'] + 1
    else:
        if revision_of and not re.search(r'_(\d{10})\.html$', Path(revision_of).name):
            raise ValueError('旧HTML缺少解析元数据')
        if revision_of:
            # Legacy filename preserves MMDDHHMMSS; caller supplies the year/date.
            stamp = re.search(r'_(\d{10})\.html$', Path(revision_of).name)[1]
            if parsed_at.strftime('%m%d%H%M%S') != stamp:
                raise ValueError('旧HTML的解析时刻与传入parsed_at不一致')
        batch_id = hashlib.sha256((content_hash + parsed_at.isoformat()).encode()).hexdigest()
        revision = 2 if revision_of else 1
    # Continue from the highest existing revision even when an earlier page is passed.
    if revision_of:
        for existing in directory.glob('人工核对表_*.html'):
            metadata = read_html_metadata(existing)
            if metadata and metadata['batch_id'] == batch_id:
                revision = max(revision, metadata['revision'] + 1)
    is_url = source.startswith(('http://', 'https://'))
    prefix = title if is_url else Path(source).stem
    # New payloads own their publication date; legacy payloads retain inference.
    saved_dates = {row['quote'].get('published_at') for row in rows
                   if 'published_at' in row.get('quote', {})}
    if len(saved_dates) > 1:
        raise ValueError('同一笔记的来源发布日期不一致')
    if saved_dates:
        saved_day = next(iter(saved_dates))
        day = date.fromisoformat(saved_day) if saved_day else None
    else:
        day = infer_publication_date(source, title, parsed_at)
    prefix = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', prefix).strip(' .')
    suffix = f'({revision})' if revision > 1 else ''
    day_stamp = day.strftime('%Y%m%d') if day else '日期待确认'
    path = directory / f'人工核对表_{day_stamp}_{prefix}_{parsed_at:%m%d%H%M}{suffix}.html'
    display_suffix = f'（{revision}）' if revision > 1 else ''
    display_title = f'《{title}》—— 解析{parsed_at:%m/%d %H:%M}{display_suffix}'
    metadata = {'batch_id': batch_id, 'content_hash': content_hash,
                'parsed_at': parsed_at.isoformat(), 'revision': revision}
    encoded = json.dumps(metadata, ensure_ascii=False).replace('<', '\\u003c')
    html = render_html(rows, display_title, day).replace(
        '</head>', '<script id="review-metadata" type="application/json">' + encoded + '</script></head>', 1)
    # Never overwrite a different parse that happens to finish in the same minute.
    with path.open('x', encoding='utf-8') as stream:
        stream.write(html)
    return path
