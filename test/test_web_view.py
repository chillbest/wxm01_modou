"""Online presentation decisions, executed as JavaScript rather than text matching."""
import subprocess
from pathlib import Path


def test_main_paste_extracts_exact_six_digits_without_restricting_typing():
    source = Path('src/modou/web/static/review.js').read_text(encoding='utf-8')
    helpers = source.split('(() => {', 1)[0]
    checks = r'''
const assert=require('node:assert/strict');
const events=[];const input={value:'old',selectionStart:3,selectionEnd:3,
 setRangeText(text,start,end,mode){assert.equal(mode,'end');this.value=this.value.slice(0,start)+text+this.value.slice(end);this.selectionStart=this.selectionEnd=start+text.length},
 dispatchEvent:e=>events.push(e.type)};
wireMainPaste(input);
function paste(text){let prevented=false;input.onpaste({preventDefault(){prevented=true},clipboardData:{getData:type=>{assert.equal(type,'text/plain');return text}}});assert.equal(prevented,true);}
paste('https://bgm.tv/subject/105697');assert.equal(input.value,'old105697');assert.deepEqual(events,['input','change']);assert.equal(input.selectionStart,9);
input.selectionStart=input.selectionEnd=0;
paste('abc123456def654321');assert.equal(input.value,'123456old105697');assert.equal(input.selectionStart,6);
input.value='111111|old|222222';input.selectionStart=7;input.selectionEnd=10;
paste('1234567 / 7654321 / 654321');assert.equal(input.value,'111111|654321|222222');assert.equal(input.selectionStart,13);assert.equal(input.selectionEnd,13);
input.value='left|right';input.selectionStart=input.selectionEnd=5;paste('subject/105697');assert.equal(input.value,'left|105697right');
input.value='replace all';input.selectionStart=0;input.selectionEnd=input.value.length;paste('subject/123456');assert.equal(input.value,'123456');
input.value='';input.selectionStart=input.selectionEnd=0;paste('subject/105697');assert.equal(input.value,'105697');
for(const text of ['12345','1234567','no digits','１２３４５６',' ']){input.value='existing';const n=events.length;paste(text);assert.equal(input.value,'existing');assert.equal(events.length,n);}
input.value='anything | 空格 ';assert.equal(input.value,'anything | 空格 ');
assert.equal(input.oninput,undefined);assert.equal(input.onkeydown,undefined);assert.equal(input.onbeforeinput,undefined);
'''
    assert 'wireMainPaste(input);input.onchange=' in source
    subprocess.run(['node', '-e', helpers + checks], check=True, capture_output=True, text=True)


def test_pink_header_search_link_opens_new_tab():
    from modou.review_html import header_stage_label
    for label in ['GameFAQs', 'FAQs', 'FAQ', '变化文字']:
        html = header_stage_label('gamefaqs', label)
        assert 'background:#FF6FAE' in html
        assert 'href="https://vgcollect.com/search"' in html
        assert 'target="_blank" rel="noopener noreferrer"' in html
        assert '>' + label + '</a></span>' in html
    assert '<a ' not in header_stage_label('alias', 'FAQs')

def test_note_button_state_and_hover_preview():
    helpers = Path('src/modou/web/static/review.js').read_text(encoding='utf-8').split('(() => {', 1)[0]
    checks = r'''
const assert=require('node:assert/strict');
globalThis.innerWidth=320;globalThis.innerHeight=600;
const handlers={},areaHandlers={},classes=new Set(),attrs={};
const summary={classList:{toggle:(key,on)=>on?classes.add(key):classes.delete(key)},
 setAttribute:(key,value)=>attrs[key]=value,removeAttribute:key=>delete attrs[key],
 addEventListener:(key,fn)=>handlers[key]=fn,
 getBoundingClientRect:()=>({left:285,top:20,bottom:45})};
const area={value:'   ',addEventListener:(key,fn)=>areaHandlers[key]=fn};
const tip={id:'tip',hidden:true,style:{},textContent:'',getBoundingClientRect:()=>({width:280,height:100})};
wireNotePreview(summary,area,tip);
assert.equal(classes.has('web-note-filled'),false);handlers.mouseenter();assert.equal(tip.hidden,true);
area.value='First line\n<script>plain text</script>';areaHandlers.input();
assert.equal(classes.has('web-note-filled'),true);handlers.mouseenter();
assert.equal(tip.hidden,false);assert.equal(tip.textContent,area.value);assert.equal(attrs['aria-describedby'],'tip');
assert.equal(tip.style.left,'28px');assert.equal(tip.style.top,'53px');
handlers.mouseleave();assert.equal(tip.hidden,true);
handlers.focus();assert.equal(tip.hidden,false);handlers.keydown({key:'Escape'});assert.equal(tip.hidden,true);
handlers.focus();handlers.click();assert.equal(tip.hidden,true);
area.value='';areaHandlers.input();assert.equal(classes.has('web-note-filled'),false);
handlers.focus();assert.equal(tip.hidden,true);assert.equal(attrs['aria-describedby'],undefined);
'''
    subprocess.run(['node', '-e', helpers + checks], check=True, capture_output=True, text=True)


def test_stage_positions_manual_targets_and_view_edit_modes():
    source = Path('src/modou/web/static/review.js').read_text(encoding='utf-8')
    helpers = source.split('(() => {', 1)[0]
    checks = r'''
const assert=require('node:assert/strict');
const row={stage_hits:{local:{id:4,name_cn:'游戏'}}};
let slots=hitStageSlots(row,{bangumi_id:'4'});
assert.deepEqual(slots.map(s=>s.candidate?.id||'-'),['-',4,'-','-','-']);
assert.deepEqual(hitStageSlots(row,{bangumi_id:'9'}).map(s=>s.candidate),[null,null,null,null,null]);
assert.equal(hitStageSlots({stage_hits:{gamefaqs:{outlink:'https://gamefaqs.gamespot.com/ps5/1-game'}}},
 {outlink:'https://gamefaqs.gamespot.com/ps5/1-game'})[4].candidate.outlink,'https://gamefaqs.gamespot.com/ps5/1-game');
assert.deepEqual(hitStageSlots(row,{}).map(s=>s.candidate),[null,null,null,null,null]);
for(const column of [4,5,7]){
 assert.equal(fieldPresentation(column,false,[['','直接购买'],['PS5','PS5']],'PS5').dropdown,false);
 assert.equal(fieldPresentation(column,true,[['','直接购买'],['PS5','PS5']],'PS5').dropdown,true);
}
const types=[['','？'],['Base','Base']];
assert.deepEqual(fieldPresentation(3,false,types,null),{dropdown:true,label:'？',unknown:true});
assert.equal(fieldPresentation(3,false,types,'Base').unknown,false);
assert.equal(fieldPresentation(5,false,[['','？'],['港版','港版']],null).unknown,true);
assert.equal(fieldPresentation(7,false,[['?','？'],['','直接购买']],'').label,'直接购买');
assert.equal(fieldPresentation(7,false,[['?','？'],['','直接购买']],'其他优惠').label,'？');
'''
    subprocess.run(['node', '-e', helpers + checks], check=True, capture_output=True, text=True)


def test_unknown_controls_and_gamefaqs_truncation():
    source = Path('src/modou/web/static/review.js').read_text(encoding='utf-8').split('(() => {', 1)[0]
    checks = r"""
const assert=require('node:assert/strict');
for(const col of [3,4,5,7]){
 const v=fieldPresentation(col,false,[['?','？'],['PS5','PS5']],null);
 assert.equal(v.dropdown,true);assert.equal(v.unknown,true);
}
assert.equal(fieldPresentation(7,false,[['?','？'],['','直接购买']],'').unknown,false);
assert.equal(gamefaqsLabel('https://gamefaqs.gamespot.com/ps5/450686-elden-ring-shadow-of-the-erdtree-edition'),'elden-ring-shadow-of…');
assert.equal(gamefaqsLabel('https://gamefaqs.gamespot.com/ps5/1-short-game'),'short-game');
assert.equal(hitStageSlots({manual_target:true,stage_hits:{local:{id:4}}},{bangumi_id:'4'}).some(s=>s.candidate),false);
"""
    subprocess.run(['node','-e',source+checks],check=True,capture_output=True,text=True)


def test_same_candidate_does_not_overwrite_other_edits():
    helpers=Path('src/modou/web/static/review.js').read_text(encoding='utf-8').split('(() => {',1)[0]
    checks=r"""
const assert=require('node:assert/strict');
const row={final:{bangumi_id:'4',type:'Expansion',note:'备注',bangumi_main:'9'},manual_fields:['final.type','final.note','final.bangumi_main']};
const same=candidateSelection(row,{id:4,name_cn:'游戏'});
assert.deepEqual(same,{manual_target:true,final:{}});
const changed=candidateSelection(row,{id:8,name_cn:'新游戏'});
assert.equal(changed.final.bangumi_id,'8');
assert.equal(changed.final.type,'Expansion');
assert.equal(changed.final.note,'备注');
assert.equal(changed.final.bangumi_main,'9');
assert.equal(sameTarget({outlink:'https://gamefaqs.gamespot.com/ps5/1-game'},{outlink:'https://gamefaqs.gamespot.com/ps5/1-game'}),true);
assert.equal(sameTarget({bangumi_id:'4'},{id:5}),false);
"""
    subprocess.run(['node','-e',helpers+checks],check=True,capture_output=True,text=True)


def test_historical_red_dropdowns_and_batch_timing():
    source=Path('src/modou/web/static/review.js').read_text(encoding='utf-8').split('(() => {',1)[0]
    timing=Path('src/modou/web/static/home.js').read_text(encoding='utf-8').split('async function refresh()',1)[0]
    checks=r"""
const assert=require('node:assert/strict');
for(const column of [3,4,5,7])assert.equal(fieldPresentation(column,false,[['','？'],['Base','Base']],'Base',true).dropdown,true);
assert.equal(batchTiming({state:'ready',parse_started_at:'2026-01-10T15:20:00+00:00',parse_elapsed_seconds:80}),'1月10日 23:20 耗时1m20s');
assert.equal(batchTiming({state:'failed',parse_started_at:'2026-01-10T15:20:00+00:00',parse_elapsed_seconds:3601}),'1月10日 23:20 耗时1h0m1s');
assert.equal(batchTiming({state:'ready'}),'--月--日 --:-- 耗时--');
assert.equal(batchTiming({state:'parsing',parse_started_at:'2026-01-10T15:20:00+00:00'},Date.parse('2026-01-10T15:20:05+00:00')),'1月10日 23:20 耗时5s');
"""
    subprocess.run(['node','-e',source+timing+checks],check=True,capture_output=True,text=True)


def test_selected_lock_disables_and_restores_controls_offline():
    source=Path('src/modou/web/static/review.js').read_text(encoding='utf-8')
    lock=source[source.index('function applyLock('):source.index("for(const selector of ['#toggle-c'")]
    harness=r"""
const assert=require('node:assert/strict');
function classes(){const values=new Set();return {contains:x=>values.has(x),toggle:(x,v)=>{if(v)values.add(x);else values.delete(x);}};}
const controls=[{disabled:false,dataset:{}},{disabled:true,dataset:{}}];
for(const c of controls)c.hasAttribute=()=>Object.hasOwn(c.dataset,'beforeLock');
const children={inert:false,querySelectorAll:()=>controls};
const actions={inert:false,querySelectorAll:()=>[]},text={inert:false,querySelectorAll:()=>[]};
const c={display:'table-row'},d={display:'grid'},original={append:s=>{state=s;}};let state=null;
const entry={classList:classes(),querySelector:s=>({'.children':children,'.web-actions':actions,'.web-original-text':text,'.detail':c,'.trace':d,'.original':original,'.web-lock-state':state})[s]};
const lockDetails=new WeakMap(),preview={hidden:false};let hoverToken=0;
const el=()=>({textContent:'',className:''});const getComputedStyle=e=>e;
"""
    checks=r"""
applyLock(entry,{selected:true,imported:false});
assert.equal(entry.classList.contains('web-locked'),true);
assert.equal(children.inert,true);assert.equal(actions.inert,true);assert.equal(text.inert,true);
assert.deepEqual(controls.map(c=>c.disabled),[true,true]);
assert.equal(preview.hidden,true);assert.equal(state.textContent,'已勾选 · 已锁定');
applyLock(entry,{selected:true,imported:false});
applyLock(entry,{selected:false,imported:false});
assert.equal(children.inert,false);assert.deepEqual(controls.map(c=>c.disabled),[false,true]);
assert.equal(entry.classList.contains('web-show-c'),true);assert.equal(entry.classList.contains('web-show-d'),true);
assert.equal(state.textContent,'');
"""
    subprocess.run(['node','-e',harness+lock+checks],check=True,capture_output=True,text=True)


def test_pending_selection_counts_and_filters():
    source=Path('src/modou/web/static/review.js').read_text(encoding='utf-8').split('(() => {',1)[0]
    checks=r"""
const assert=require('node:assert/strict');
const rows=[{imported:true,selected:true},...Array.from({length:7},()=>({selected:false}))];
assert.deepEqual(selectionCounts(rows),{selected:0,pending:7,imported:1,total:8});
rows[1].selected=true;
assert.deepEqual(selectionCounts(rows),{selected:1,pending:7,imported:1,total:8});
assert.equal(rowHidden(rows[0],true,false),false);
assert.equal(rowHidden(rows[1],true,false),true);
assert.equal(rowHidden(rows[2],true,false),false);
assert.equal(rowHidden(rows[0],true,true),true);
rows[1].already_imported=true;
assert.deepEqual(selectionCounts(rows),{selected:0,pending:6,imported:2,total:8});
assert.equal(rowHidden(rows[1],true,false),false);
assert.deepEqual(selectionCounts([{imported:true},{already_imported:true}]),{selected:0,pending:0,imported:2,total:2});
assert.deepEqual(selectionCounts([]),{selected:0,pending:0,imported:0,total:0});
assert.equal(storedTableLabel({table:'game_alias',operation:'新增'}),'别名表（game_alias）新增');
assert.equal(storedTableLabel({table:'game_product_config',operation:'复用'}),'GPC表（Game Product Configuration）复用');
assert.equal(storedTableLabel({table:'m_low_record',operation:'新增/复用未记录'}),'报价表（m_low_record）新增/复用未记录');
"""
    subprocess.run(['node','-e',source+checks],check=True,capture_output=True,text=True)


def test_reparse_precedes_restore_in_dom():
    source=Path('src/modou/web/static/review.js').read_text(encoding='utf-8')
    fn=source[source.index('function wireReparse('):source.index('async function replaceEntry(')]
    checks=r"""
const assert=require('node:assert/strict');
let actions;
const el=(tag,text)=>({textContent:text,append(...children){this.children=children}});
const d={append(node){actions=node}};
const entries=[{querySelector:s=>s==='.web-d'?d:null}],batch={rows:[{}]};
wireReparse(0);
assert.deepEqual(actions.children.map(b=>b.textContent),['重新解析','Restore']);
"""
    subprocess.run(['node','-e',fn+checks],check=True,capture_output=True,text=True)
