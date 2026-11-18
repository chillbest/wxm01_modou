from datetime import datetime
from modou.review_html import publication_day, render_html, write_html
from test_review_table import row


def test_html_geometry_trace_and_colors():
    r=row();r['stage_trace']=[{'stage':'本地别名','result':'未命中','reason':'无匹配候选'}]
    text=render_html([r],'<标题>',datetime(2026,11,3))
    assert text.count('<colgroup>')==2
    assert 'background:#00C2D1;color:#000' in text
    assert '【命中情况】' in text and '未命中' in text
    assert '&lt;标题&gt;' in text
    assert '1. 🔸游戏' in text


def test_date_uses_filename_then_title():
    now=datetime(2026,11,14,20,40,12)
    assert str(publication_day('11.3｜Ps好价','',now))=='2026-11-03'
    assert str(publication_day('','出价日2025/10/12',now))=='2025-10-12'


def test_updated_spacing_and_unmatched_strike():
    r=row(); r['stage_hits']={}
    html=render_html([r],'title',datetime(2026,11,3))
    assert 'padding:24px 100px' in html
    assert '.trace{color:#b9c8db;font-size:16px' in html
    assert '<td class="platform" style="background:#F53535;color:#000">？</td>' in html
    assert '<div class="children"><table>' in html
    assert '<span class="trace-label">【命中情况】</span>' in html
    assert '<span class="trace-stage-name">BGM 本地</span> —— </span>' in html


def test_hide_only_skipped_after_hit():
    r=row()
    r['stage_trace']=[
        {'stage':'本地别名','result':'未命中','reason':'无匹配候选'},
        {'stage':'Bangumi本地资料','result':'命中','reason':'唯一候选'},
        {'stage':'BangumiAPI','result':'未执行','reason':'前序阶段唯一命中'},
        {'stage':'DeepSeek','result':'未执行','reason':'前序阶段唯一命中，命中即停止'}]
    html=render_html([r],'title',datetime(2026,11,3))
    assert '别名库</span> —— </span><span class="trace-content">未命中' in html
    assert 'BGM 本地</span> —— </span><span class="trace-content">命中' in html
    assert 'BGM API——' not in html and 'DeepSeek——' not in html
    assert len(r['stage_trace']) == 4


def test_gray_separators_center_and_candidates():
    r=row();r['stage_trace']=[{'stage':'Bangumi本地资料','result':'歧义','reason':'多个候选','candidates':[{'id':4,'name_cn':'one'},{'id':5,'name_cn':'two'}]}]
    html=render_html([r],'title',datetime(2026,11,3))
    assert '<span class="hit-muted"> / </span>' in html
    assert '<span class="hit-muted">-</span>' in html
    assert 'td{text-align:center}' in html
    assert 'one' in html and 'two' in html and 'subject/5' in html


def test_review_controls_behaviour():
    import re
    import subprocess
    html=render_html([row(),row()],'title',datetime(2026,11,3))
    assert 'position:sticky;top:0' in html
    assert html.count('role="switch"') == 3
    assert '🧹 清除全部' in html and '👁️ 显示全部' in html and '⬜ 仅看未选' in html
    assert '↗️ 导出ALL未选' in html
    assert html.count('type="checkbox"') == 2
    assert 'grid-template-columns:10em minmax(0,1fr);column-gap:0.25em' in html
    script=re.findall(r'<script>(.*?)</script>',html,re.S)[-1]
    harness='''
const assert=require('node:assert/strict');
const checks=[0,1].map(()=>({checked:false,addEventListener(t,fn){this.change=fn}}));
const entries=checks.map((c,i)=>({hidden:false,querySelector(s){return s==='.review-check'?c:{textContent:(i+1)+'. original'}},querySelectorAll(){return ['name','- / - / - / hit','123','待确认Base rebase Expansion母子集合集','PS5','HK','100','discount'].map(textContent=>({textContent}))}}));
const buttons={};
for(const id of ['clear-selection','show-unchecked','show-all','selection-status','toggle-c','toggle-d','show-details','export-unchecked','export-dialog','export-text','copy-status','close-export','copy-export','export-count']) buttons['#'+id]={setAttribute(){}};
global.document={body:{classList:{values:new Set(),toggle(k){if(this.values.has(k)){this.values.delete(k);return false}this.values.add(k);return true},remove(...keys){keys.forEach(k=>this.values.delete(k))}}},querySelectorAll(){return entries},querySelector(s){return buttons[s]}};
'''+script+'''
checks[0].checked=true;checks[0].change();
buttons['#show-unchecked'].onclick();
assert.equal(entries[0].hidden,true);assert.equal(entries[1].hidden,false);
buttons['#show-unchecked'].onclick();assert.equal(entries[0].hidden,false);
buttons['#show-all'].onclick();assert.equal(entries[0].hidden,false);
buttons['#show-unchecked'].onclick();buttons['#clear-selection'].onclick();
assert(checks.every(c=>!c.checked));assert(entries.every(e=>!e.hidden));
buttons['#toggle-c'].onclick();assert(document.body.classList.values.has('hide-c'));
buttons['#toggle-d'].onclick();assert(document.body.classList.values.has('hide-d'));
buttons['#show-details'].onclick();assert.equal(document.body.classList.values.size,0);
buttons['#export-dialog'].showModal=()=>{};
checks[0].checked=true;buttons['#export-unchecked'].onclick();
assert.equal(buttons['#export-text'].value,'2. original\\nname——_/_/_/hit——PS5——HK——100——discount');
assert.equal(buttons['#export-count'].textContent,'共1条');
checks[0].checked=false;buttons['#export-unchecked'].onclick();
assert.equal(buttons['#export-count'].textContent,'共2条');
assert(buttons['#export-text'].value.includes('\\n\\n\\n'));

'''
    subprocess.run(['node','-e',harness],check=True,capture_output=True,text=True)


def test_candidate_code_and_concise_status():
    r=row();r['stage_trace']=[{'stage':'本地别名','result':'未命中','reason':'无匹配候选'}, {'stage':'Bangumi本地资料','result':'歧义','reason':'多个候选','candidates':[{'id':4,'name_cn':'one'},{'id':5,'name_cn':'two'}]}]
    html=render_html([r],'title',datetime(2026,11,3))
    assert html.count('<code class="candidate-code">') == 2
    assert 'subject/4' in html and 'subject/5' in html
    assert '未命中；无匹配候选' not in html
    assert '歧义；多个候选' not in html


def test_gold_hit_and_stage_header():
    html=render_html([row()],'title',datetime(2026,11,3))
    assert '<code class="matched-gold">' in html
    assert html.count('<span class="stage-label"') == 5
    assert 'DeepSeek辅助' in html
    assert '>C行=问题详情</button>' in html
    assert '>D行=命中详情</button>' in html


def test_header_omits_unmatched_legend():
    html=render_html([row()],'title',datetime(2026,11,3))
    assert 'background:#F53535;color:#000;text-decoration:line-through">未命中</span>' not in html


def test_header_and_status_font_sizes():
    html=render_html([row()],'title',datetime(2026,11,3))
    assert '.toolbar-status{align-self:center;font-size:13px}' in html
    assert '.sticky-header,.sticky-header *{font-size:13px}' in html


def test_all_links_open_new_tab():
    import re
    r=row();r['stage_trace']=[{'stage':'Bangumi本地资料','result':'命中','reason':'唯一候选','candidates':[{'id':4,'name_cn':'game'}]}]
    html=render_html([r],'title',datetime(2026,11,3))
    assert '<base target="_blank">' in html
    links=re.findall(r'<a [^>]+>',re.sub(r'<script\b[^>]*>.*?</script>', '', html, flags=re.S))
    assert links
    assert all('target="_blank"' in link and 'rel="noopener noreferrer"' in link for link in links)


def test_stage_dashes_share_fixed_column():
    html=render_html([row()],'title',datetime(2026,11,3))
    assert 'grid-template-columns:10em minmax(0,1fr);column-gap:0.25em' in html
    assert '.trace-stage{text-align:right;white-space:pre}' in html
    assert html.count('class="trace-stage"') == 5


def test_compact_requires_both_details_hidden():
    html=render_html([row()],'title',datetime(2026,11,3))
    assert 'body.hide-c.hide-d .entry{margin-top:10px;margin-bottom:12px}' in html
    assert '.trace-stage-name{font-size:14px;font-weight:700}' in html


def test_compact_b_row_and_badge_padding():
    html=render_html([row()],'title',datetime(2026,11,3))
    assert 'body.hide-c.hide-d .b-row td{padding-top:2px;padding-bottom:2px;line-height:1.25}' in html
    assert 'body.hide-c.hide-d .b-row .matched-gold{padding-top:0;padding-bottom:0;margin-top:0;margin-bottom:0;line-height:1.25}' in html


def test_only_hit_stage_label_is_colored():
    r=row()
    html=render_html([r],'title',datetime(2026,11,3))
    assert 'class="trace-stage-name" style="background:#00C2D1;color:#000;border-radius:4px">BGM 本地' in html
    assert 'class="trace-stage-name">别名库' in html
    r['stage_hits']={}
    assert 'class="trace-stage-name" style=' not in render_html([r],'title',datetime(2026,11,3))


def test_proposed_alias_mapping_only_after_alias_miss():
    r=row();r['stage_trace']=[{'stage':'本地别名','result':'未命中','reason':'无匹配候选'}]
    html=render_html([r],'title',datetime(2026,11,3))
    assert '拟增' in html
    assert html.count('<code class="alias-preview-code">') == 2
    assert 'background:#1b2939;color:#91a8be' in html
    r['stage_hits']={}
    assert '拟增' not in render_html([r],'title',datetime(2026,11,3))
    r['stage_hits']={'alias':{'gpc_id':1,'name_zh':'游戏'}}
    assert '拟增' not in render_html([r],'title',datetime(2026,11,3))


def test_gamefaqs_fifth_slot_and_problem_detail():
    r = row()
    link = 'https://gamefaqs.gamespot.com/ps5/324823-ghost-of-tsushima-iki-island'
    candidate = {'name_zh': '壹岐岛', 'outlink': link}
    r['stage_hits'] = {'gamefaqs': candidate}
    r['stage_trace'] = [{'stage': 'GameFAQs', 'result': 'AI建议', 'reason': '待人工确认', 'candidates': [candidate]}]
    html = render_html([r], 'title', datetime(2026,11,3))
    assert html.count('<span class="hit-muted"> / </span>') == 4
    assert 'background:#FF6FAE;color:#000' in html
    assert 'GameFAQs</span> ——' in html and link in html
    assert '<tr class="detail"><td colspan="8">——' in html
    assert 'problem-summary' not in html
    assert 'GameFAQs链接待人工核实' in html
    r['stage_hits'] = {'api': {'id': 606810, 'name_cn': '空之轨迹 the 2nd'}}
    html = render_html([r], 'title', datetime(2026,11,3))
    assert '</code><span class="hit-muted"> / </span><span class="hit-muted">-</span><span class="hit-muted"> / </span><span class="hit-muted">-</span>' in html


def test_eight_columns_gpc_values_and_disabled_type():
    import re
    from copy import deepcopy
    from modou.models import GPC_TYPES
    r = row()
    r['stage_hits']['local'].update(gpc_id=1, bangumi_main='123', type='Expansion')
    r['final'] = {'bangumi_main': None, 'type': None}
    before = deepcopy(r)
    html = render_html([r], 'title', datetime(2026,11,3))
    assert re.findall(r'<th>(.*?)</th>', html)[2:] == ['main', 'type', '平台', '地区', '价格', '优惠方式']
    assert '问题简述' not in html and '详见下行' not in html
    assert html.count('<col style=') == 16
    cells = re.findall(r'<td[^>]*>(.*?)</td>', html.split('<tr class="b-row">')[1].split('</tr>')[0])
    assert len(cells) == 8 and 'href="https://bgm.tv/subject/123"' in cells[2] and cells[4] == 'PS5'
    assert '<select class="gpc-type" aria-label="GPC type" disabled>' in cells[3]
    assert '<option value="Expansion" selected>Expansion</option>' in cells[3]
    assert '.gpc-type:disabled{' in html
    assert 'text-align:center;text-align-last:center}.gpc-type option{text-align:center}' in html
    assert r == before
    for value in (*GPC_TYPES, None):
        r['final'] = {'bangumi_main': '456', 'type': value}
        r['stage_hits']['local']['type'] = value
        html = render_html([r], 'title', datetime(2026,11,3))
        assert '<a href="https://bgm.tv/subject/456" target="_blank" rel="noopener noreferrer">（456）</a>' in html
        assert '<option value="' + (value or '') + '" selected>' in html


def test_missing_gpc_fields_and_changed_target_do_not_invent_values():
    r = row()
    html = render_html([r], 'title', datetime(2026,11,3))
    assert '<option value="" selected>待确认</option>' in html
    assert '<option value="Base" selected>' not in html
    r['stage_hits']['local'].update(gpc_id=1, bangumi_id='4', bangumi_main='123', type='Base')
    r['final'] = {'gpc_id': 2, 'bangumi_main': None, 'type': None}
    html = render_html([r], 'title', datetime(2026,11,3))
    assert 'href="https://bgm.tv/subject/123"' not in html and '<option value="Base" selected>' not in html
    r['final'] = {'bangumi_main': '<script>bad()</script>', 'type': '"><script>bad()</script>'}
    html = render_html([r], 'title', datetime(2026,11,3))
    assert '<script>bad()' not in html and '&lt;script&gt;bad()' in html


def test_all_problems_only_appear_in_c_row():
    r = row()
    assert '<tr class="detail">' not in render_html([r], 'title', datetime(2026,11,3))
    for issues in (['短问题'], ['1234567890'], ['12345678901', '<script>', '12345678901']):
        r['errors'] = issues
        html = render_html([r], 'title', datetime(2026,11,3))
        b_row = html.split('<tr class="b-row">')[1].split('</tr>')[0]
        assert issues[0] not in b_row
        assert '<tr class="detail"><td colspan="8">——' in html
        detail = html.split('<tr class="detail">')[1].split('</tr>')[0]
        assert detail.count(issues[0]) == 1
        assert '<script>' not in detail


def test_main_column_links_to_main_subject_instead_of_matched_subject():
    import re
    for main_id in ('123', 123):
        r = row()
        r['final'] = {'bangumi_main': main_id}
        html = render_html([r], 'title', datetime(2026,11,3))
        assert '<th>main</th>' in html and '<th>BGM_main</th>' not in html
        cells = re.findall(r'<td[^>]*>(.*?)</td>', html.split('<tr class="b-row">')[1].split('</tr>')[0])
        assert cells[2] == '<a href="https://bgm.tv/subject/123" target="_blank" rel="noopener noreferrer">（123）</a>'
        assert 'https://bgm.tv/subject/4' in cells[1]


def test_missing_or_invalid_main_subject_does_not_create_link():
    import re
    for main_id in (None, '', '１２３', '123/other', '\"><script>bad()</script>'):
        r = row()
        r['final'] = {'bangumi_main': main_id}
        html = render_html([r], 'title', datetime(2026,11,3))
        cells = re.findall(r'<td[^>]*>(.*?)</td>', html.split('<tr class="b-row">')[1].split('</tr>')[0])
        assert '<a ' not in cells[2] and '<script>' not in cells[2]
        if main_id is None:
            assert cells[2] == '<span style="background:#F53535;color:#000;font-weight:700">？</span>'
            assert '<td class="main-unknown" style="background:#F53535;color:#000;font-weight:700">' in html


def test_bangumi_subject_type_never_becomes_gpc_type():
    import re
    from copy import deepcopy
    for stage in ('local', 'api', 'ds', 'gamefaqs'):
        for subject_type in (4, '4', 'Base'):
            r = row()
            r['stage_hits'] = {stage: {'id': 4, 'name_cn': '游戏', 'type': subject_type}}
            r['final'] = {'bangumi_main': None, 'type': None}
            before = deepcopy(r)
            html = render_html([r], 'title', datetime(2026,11,3))
            dropdown = re.search(r'<select.*?</select>', html).group()
            assert '<option value="" selected>待确认</option>' in dropdown
            assert 'value="4"' not in dropdown
            assert len(re.findall('<option ', dropdown)) == 6
            assert r == before


def test_gpc_alias_and_final_product_types_are_preserved():
    from modou.models import GPC_TYPES
    for value in GPC_TYPES:
        r = row()
        r['stage_hits'] = {'alias': {'gpc_id': 1, 'name_zh': '游戏', 'type': value}}
        html = render_html([r], 'title', datetime(2026,11,3))
        assert '<option value="' + value + '" selected>' in html
        r['stage_hits'] = {'api': {'id': 4, 'type': 4}}
        r['final'] = {'type': value}
        html = render_html([r], 'title', datetime(2026,11,3))
        assert '<option value="' + value + '" selected>' in html


def test_invalid_product_type_cannot_add_dropdown_options():
    from modou.review_html import type_dropdown
    for value in (4, '4', 'unknown', '<script>'):
        dropdown = type_dropdown(value)
        assert '<option value="" selected>待确认</option>' in dropdown
        assert dropdown.count('<option ') == 6
        r = row()
        r['final'] = {'type': value}
        html = render_html([r], 'title', datetime(2026,11,3))
        assert dropdown in html


def test_five_stage_details_stop_after_hit():
    stages = [('本地别名', 'alias', '别名库'), ('Bangumi本地资料', 'local', 'BGM 本地'),
              ('BangumiAPI', 'api', 'BGM API'), ('DeepSeek', 'ds', 'DeepSeek'), ('GameFAQs', 'gamefaqs', 'GameFAQs')]
    for winner in range(5):
        r = row()
        candidate = {'id': 4, 'name_cn': '游戏'} if winner < 4 else {'name_zh': '游戏', 'outlink': 'https://gamefaqs.gamespot.com/ps5/1-game'}
        r['stage_hits'] = {stages[winner][1]: candidate}
        r['stage_trace'] = [dict(stage=name, result='未命中' if i < winner else '命中' if i == winner else '未执行',
                                 reason='无匹配候选' if i < winner else '唯一候选' if i == winner else '前序阶段唯一命中，命中即停止',
                                 candidates=[candidate] if i == winner else []) for i, (name, _, _) in enumerate(stages)]
        html = render_html([r], 'title', datetime(2026,11,3))
        trace = html.split('<div class="trace">', 1)[1].split('</section>', 1)[0]
        assert trace.count('class="trace-stage"') == winner + 1
        for _, _, label in stages[winner+1:]:
            assert '>' + label + '</span>' not in trace



def test_html_revision_preserves_parse_time_and_content():
    import uuid
    from pathlib import Path
    import pytest
    from modou.review_html import read_html_metadata
    directory = Path('.tmp') / ('html-revisions-' + uuid.uuid4().hex)
    directory.mkdir(parents=True)
    parsed = datetime(2026,11,15,20,51,27)
    source = 'data/11.3A｜Ps好价光盘.txt'
    first = write_html([row()], source, '11.3｜Ps好价光盘', directory, now=parsed)
    assert first.name == '人工核对表_20261103_11.3A｜Ps好价光盘_11152051.html'
    assert '<h1>《11.3｜Ps好价光盘》—— 解析11/15 20:51</h1>' in first.read_text(encoding='utf-8')
    second = write_html([row()], source, '11.3｜Ps好价光盘', directory,
                        now=datetime(2026,11,16,9), revision_of=first)
    assert second.name.endswith('_11152051(2).html')
    assert '<title>《11.3｜Ps好价光盘》—— 解析11/15 20:51（2）</title>' in second.read_text(encoding='utf-8')
    assert read_html_metadata(second)['parsed_at'] == '2026-11-15T20:51:27+08:00'
    third = write_html([row()], source, '11.3｜Ps好价光盘', directory, revision_of=first)
    assert third.name.endswith('_11152051(3).html')
    assert read_html_metadata(first)['batch_id'] == read_html_metadata(third)['batch_id']
    fresh = write_html([row()], source, '11.3｜Ps好价光盘', directory, now=datetime(2026,11,16,9))
    assert fresh.name.endswith('_11160900.html') and read_html_metadata(fresh)['revision'] == 1
    assert read_html_metadata(fresh)['batch_id'] != read_html_metadata(first)['batch_id']
    changed = row(); changed['raw_name'] = '另一游戏'
    with pytest.raises(ValueError, match='内容不同'):
        write_html([changed], source, '11.3｜Ps好价光盘', directory, revision_of=first)
    before = first.read_bytes()
    with pytest.raises(FileExistsError):
        write_html([row()], source, '11.3｜Ps好价光盘', directory, now=parsed)
    assert first.read_bytes() == before


def test_legacy_html_revision_and_url_filename():
    import uuid
    from pathlib import Path
    from modou.review_html import read_html_metadata
    directory = Path('.tmp') / ('html-legacy-' + uuid.uuid4().hex)
    directory.mkdir(parents=True)
    old = directory / '人工核对表_出价日2026-11-03_11.3A_1115205127.html'
    old.write_text('<html>original</html>', encoding='utf-8')
    output = write_html([row()], 'https://example.com/post', '11.3｜PS光盘', directory,
                        parsed_at=datetime(2026,11,15,20,51,27), revision_of=old)
    assert output.name == '人工核对表_20261103_11.3｜PS光盘_11152051(2).html'
    assert read_html_metadata(output)['revision'] == 2
    assert old.read_text(encoding='utf-8') == '<html>original</html>'



def test_hit_color_moves_to_name_and_platform_has_own_style():
    r = row()
    html = render_html([r], 'title', datetime(2026,11,3))
    assert '<td class="hit-name" style="background:#00C2D1;color:#000">游戏</td>' in html
    assert '<td>PS5</td>' in html
    r['quote']['platform'] = 'PS4'
    html = render_html([r], 'title', datetime(2026,11,3))
    assert '<td class="platform" style="background:#64748B;color:#000">PS4</td>' in html
    r['stage_hits'] = {}
    r['quote']['platform'] = 'PS5'  # Old payload's default must not imply a match.
    html = render_html([r], 'title', datetime(2026,11,3))
    assert '<td class="hit-name" style="background:#F53535;color:#000">游戏</td>' in html
    assert '<td class="platform" style="background:#F53535;color:#000">？</td>' in html
    assert '<td>PS5</td>' not in html


def test_interaction_templates_are_safe_and_stage_specific():
    r=row()
    r['stage_trace']=[{'stage':s,'result':'未命中','reason':'AI未选择候选'} for s in ('DeepSeek','GameFAQs')]
    r['ai_interactions']=[{'stage':'DeepSeek','system':'</template><script>alert(1)</script>','user':'FIRST','raw_response':'RAW1','content':'reply\nline'}, {'stage':'GameFAQs','system':'second','user':'SECOND','raw_response':'RAW2'}]
    html=render_html([r],'title',datetime(2026,11,3))
    assert '</template><script>alert(1)' not in html
    assert '&lt;script&gt;alert(1)' in html
    assert 'data-detail="ai-1-DeepSeek"' in html and 'data-detail="ai-1-GameFAQs"' in html
    first=html.split('<template id="ai-1-DeepSeek">')[1].split('</template>')[0]
    assert 'FIRST' in first and 'SECOND' not in first
    assert 'reply\nline' in first and '<br>' not in first
    r.pop('ai_interactions')
    assert '本次交互详情未记录' in render_html([r],'title',datetime(2026,11,3))


def test_popup_hover_and_format_behaviour():
    import re, subprocess
    html=render_html([row()],'title',datetime(2026,11,3))
    script=re.findall(r'<script>(.*?)</script>',html,re.S)[0]
    harness=r''' 
const assert=require('node:assert/strict');
function element(){return {handlers:{},style:{},offsetWidth:600,offsetHeight:300,hidden:true,setAttribute(k,v){this[k]=v;},addEventListener(k,f){this.handlers[k]=f;}};}
const popup=element(), text=element(), close=element(), format=element(), wrap=element(), trigger=element();
let pres=[];
text.replaceChildren=items=>{pres=items;};text.querySelectorAll=s=>s==='pre'?pres:[];
trigger.contains=()=>false;trigger.closest=()=>null;trigger.dataset={detail:'ai-1-DeepSeek'};trigger.getBoundingClientRect=()=>({left:50,bottom:120});
let pending=null;
global.setTimeout=f=>{pending=f;return 1;};global.clearTimeout=()=>{pending=null;};
global.innerWidth=1000;global.innerHeight=700;
const elements={'#ai-popup':popup,'#ai-text':text,'#ai-close':close,'#ai-format':format,'#ai-wrap':wrap};
global.document={handlers:{},querySelector:s=>elements[s],querySelectorAll:()=>[trigger],getElementById:()=>({content:{cloneNode:()=>['system\nline','{"a":1}','{"candidate":null}','{"choices":[]}'].map(value=>Object.assign(element(),{textContent:value,parentElement:{querySelector(){return this.button;},button:element()}}))}}),addEventListener(k,f){this.handlers[k]=f;}};
'''
    checks=r'''
document.handlers.mouseover({target:{closest:selector=>selector==='.ai-trigger'?trigger:null}});assert.equal(popup.hidden,false);assert.equal(pres.length,4);
assert.equal(pres[1].textContent,'{"a":1}');assert.equal(pres[1].style.whiteSpace,'pre');
document.handlers.mouseout({target:{closest:()=>trigger}});assert(pending);popup.handlers.mouseenter();assert.equal(pending,null);
format.onclick();assert(pres[1].textContent.includes('  "a": 1'));assert.equal(pres[0].textContent,'system\nline');
pres[1].parentElement.button.onclick();assert.equal(pres[1].style.whiteSpace,'pre-wrap');assert.equal(pres[0].style.whiteSpace,'pre');assert.equal(wrap.textContent,'All换行');
wrap.onclick();assert(pres.every(p=>p.style.whiteSpace==='pre-wrap'));assert.equal(wrap.textContent,'All不换行');
format.onclick();assert.equal(pres[1].textContent,'{"a":1}');assert.equal(pres[1].style.whiteSpace,'pre-wrap');
wrap.onclick();assert(pres.every(p=>p.style.whiteSpace==='pre'));assert.equal(wrap.textContent,'All换行');
wrap.onclick();format.onclick();
popup.handlers.mouseleave();pending();assert.equal(popup.hidden,true);
document.handlers.mouseover({target:{closest:selector=>selector==='.ai-trigger'?trigger:null}});assert.equal(pres[1].style.whiteSpace,'pre');assert.equal(pres[1].textContent,'{"a":1}');
document.handlers.keydown({key:'Escape'});assert.equal(popup.hidden,true);
'''
    subprocess.run(['node','-e',harness+script+checks],check=True,capture_output=True,text=True)


def test_reply_cards_and_scroll_scope():
    r=row()
    r['stage_trace']=[{'stage':'DeepSeek','result':'未命中','reason':'test'}]
    r['ai_interactions']=[{'stage':'DeepSeek','system':'system','user':'user','content':'reply','raw_response':'raw'}]
    html=render_html([r],'title',datetime(2026,11,3))
    assert html.count('<section class="ai-block')==4
    assert '<section class="ai-block ai-reply">' in html
    assert 'background:#34252f;border-color:#8a6277' in html
    assert 'overflow-x:auto;overflow-y:hidden;max-height:none' in html
    assert 'overflow-y:auto;overflow-x:hidden' in html


def test_popup_scrollbars_use_dark_palette_only_inside_popup():
    html=render_html([row()],'title',datetime(2026,11,3))
    assert '.ai-popup,.ai-popup pre{color-scheme:dark;scrollbar-color:#9e9e9e #2b2b2b}' in html
    assert '.ai-popup::-webkit-scrollbar,.ai-popup pre::-webkit-scrollbar{width:12px;height:12px}' in html
    assert '::-webkit-scrollbar-track{background:#2b2b2b}' in html
    assert '::-webkit-scrollbar-thumb{background:#9e9e9e;border:2px solid #2b2b2b;border-radius:8px}' in html
    assert 'overflow-x:auto;overflow-y:hidden;max-height:none' in html


def test_icon_toolbar_and_independent_wrap_buttons():
    r=row();r['stage_trace']=[{'stage':'DeepSeek','result':'未命中','reason':'test'}]
    r['ai_interactions']=[{'stage':'DeepSeek','system':'s','user':'u','content':'c','raw_response':'r'}]
    html=render_html([r],'title',datetime(2026,11,3))
    assert html.count('class="ai-block-wrap"')==4
    assert 'justify-content:flex-start' in html
    close=html.split('id="ai-close"')[1].split('</button>')[0]
    assert '<svg ' in close and '>关闭<' not in close
    assert '>All换行</button>' in html


def test_three_line_summary_matches_saved_evidence():
    from modou.review_html import interaction_summary
    r=row(); r['extracted']={'raw_line':'🔹空之轨迹2nd｜🇭🇰247'}
    candidates=[{'id':606810,'name_cn':'空之轨迹 the 2nd'},{'id':509947,'name_cn':'空之轨迹 the 1st'}]
    r['stage_trace']=[{'stage':'BangumiAPI','result':'歧义','candidates':candidates},{'stage':'DeepSeek','result':'AI建议'}]
    r['stage_hits']={'ds':candidates[0]}
    summary=interaction_summary(r,1,'DeepSeek')
    assert summary.count('class="ai-summary-line"')==3
    assert '1. 🔹空之轨迹2nd｜🇭🇰247' in summary
    assert 'BGM API歧义：' in summary
    assert 'DeepSeek选择：</span><span class="ai-summary-value"><code class="ai-summary-badge ai-summary-selected">空之轨迹 the 2nd（<u>606810</u>）' in summary
    assert 'ai-summary-selected' not in interaction_summary(r,1,'GameFAQs')
    r['stage_hits']={};r['stage_trace'][-1]['result']='未命中'
    assert 'DeepSeek选择：</span><span class="ai-summary-value">未选择候选' in interaction_summary(r,1,'DeepSeek')
    r['extracted']['raw_line']='<script>bad()</script>\nline'
    assert '<script>' not in interaction_summary(r,1,'DeepSeek')


def test_summary_wrap_alignment_and_italic_originals():
    html=render_html([row()],'title',datetime(2026,11,3))
    assert '.original{font-size:18px;font-weight:600;font-style:italic;' in html
    assert '.ai-summary{font:12px/1.5 system-ui;color:#a6b5cb;' in html
    assert 'grid-template-columns:max-content minmax(0,1fr)' in html
    css=html.split('.ai-summary{')[1].split('</style>')[0]
    assert 'overflow-x:auto' not in css and 'white-space:nowrap;width:max-content' not in css
    assert 'font-size:14px;font-weight:700;font-style:italic' in css
    assert 'font:inherit' in css


def test_adaptive_header_selects_longest_fitting_and_wraps():
    import subprocess
    from modou.review_html import adaptive_hit_header
    script = adaptive_hit_header().removeprefix('<script id="adaptive-hit-header">').removesuffix('</script>')
    harness = r"""
const assert=require('node:assert/strict');
let observer, resize, fonts;
const measured=[];
const probe={style:{},innerHTML:'',getBoundingClientRect(){
 if(!measured.includes(this.innerHTML)) measured.push(this.innerHTML);
 return {width:600-measured.indexOf(this.innerHTML)*80};
}};
const header={clientWidth:640,style:{},dataset:{},appendChild(){},innerHTML:''};
global.document={querySelector:()=>header,createElement:()=>probe,fonts:{ready:{then(fn){fonts=fn;}}}};
global.window={addEventListener(name,fn){resize=fn;}};
global.getComputedStyle=()=>({paddingLeft:'10',paddingRight:'10'});
global.ResizeObserver=class{constructor(fn){observer=fn;} observe(){}};
"""
    checks = r"""
assert.equal(header.dataset.variant,'1');
for(let i=0;i<6;i++){
 header.clientWidth=620-i*80; observer();
 assert.equal(header.dataset.variant,String(i+1));
 assert.equal(header.style.whiteSpace,'nowrap');
}
header.clientWidth=200;resize();
assert.equal(header.dataset.variant,'6');
assert.equal(header.style.whiteSpace,'normal');
header.clientWidth=640;fonts();
assert.equal(header.dataset.variant,'1');
assert.ok(header.innerHTML.endsWith('）⛔'));
assert.ok(measured[5].includes('>FAQ</a></span>)'));
for(const html of measured){assert.equal((html.match(/href="https:\/\/vgcollect.com\/search"/g)||[]).length,1);assert.ok(html.includes('target="_blank" rel="noopener noreferrer"'));}
"""
    subprocess.run(['node','-e',harness+script+checks],check=True,capture_output=True,text=True)
