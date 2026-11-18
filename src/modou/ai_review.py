"""Batch evidence uses the existing AI block styles and popup controls."""
from html import escape


def record_html(record):
    parts = ['<p class="ai-call">调用：' + escape(str(record.get('call_id', ''))) + '</p>']
    for number, (key, title) in enumerate((('system', 'System提示词'), ('user', 'User内容'),
                                          ('content', '模型回复原文'), ('raw_response', 'HTTP响应原文')), 1):
        value = record.get(key)
        if value is None:
            value = '未收到或无法提取；' + str(record.get('error') or '无正文')
        parts.append('<section class="ai-block' + (' ai-reply' if key == 'content' else '')
                     + '"><h3><span>' + f'{number:02d}' + '</span> ' + title
                     + '<button type="button" class="ai-block-wrap" aria-label="换行" title="换行"></button></h3><pre>'
                     + escape(str(value)) + '</pre></section>')
    parts.append('<p class="ai-call">状态：' + escape(str(record.get('status')))
                 + '；' + escape(str(record.get('error') or '')) + '</p>')
    return ''.join(parts)


def group_html(group):
    gid = escape(group['id'], quote=True)
    label = f"AI建议 · {group['start']:02d}—{group['end']:02d}"
    parts = [f'<div class="ai-group" data-group="{gid}" data-start="{group["start"]}" data-end="{group["end"]}">',
             '<div class="ai-group-divider"><span></span><button type="button" class="ai-trigger" '
             f'data-detail="ai-{gid}" aria-label="{label}">{label}</button><span></span></div>',
             f'<template id="ai-{gid}"><div class="ai-tabs" role="tablist" aria-label="AI阶段">']
    labels = ('名称识别', 'GameFAQs', 'main识别')
    for i, label in enumerate(labels):
        parts.append(f'<button type="button" role="tab" id="{gid}-tab-{i}" data-ai-tab="{i}" '
                     f'aria-controls="{gid}-panel-{i}" aria-selected="{str(i == 0).lower()}">{label}</button>')
    parts.append('</div>')
    for i, stage in enumerate(group['stages']):
        parts.append(f'<div role="tabpanel" id="{gid}-panel-{i}" aria-labelledby="{gid}-tab-{i}" data-ai-panel="{i}"'
                     + (' hidden' if i else '') + '>')
        status = '未执行' if stage['status'] == 'skipped' else stage['status']
        parts.append('<p class="ai-call">涉及条目：' + escape('、'.join(stage['item_ids']) or '无')
                     + '；状态：' + escape(status) + '</p>')
        parts.extend(record_html(r) for r in stage['interactions'])
        if stage.get('errors'):
            parts.append('<p class="ai-call">' + escape(str(stage['errors'])) + '</p>')
        if not stage['interactions'] and stage['status'] != 'skipped':
            parts.append('<p>本次交互详情未记录</p>')
        parts.append('</div>')
    parts.append('</template></div>')
    return ''.join(parts)
